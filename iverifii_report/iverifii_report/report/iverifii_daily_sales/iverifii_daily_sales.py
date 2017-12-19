# Copyright (c) 2013, nchenbang@iverifii and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _, scrub
from frappe.utils import getdate, nowdate, flt, cint

DATE_FORMAT = "%Y-%m-%d"

class IverifiiDailySales(object):
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})
		self.filters.start_date = getdate(self.filters.selected_date[0] if self.filters.selected_date else nowdate())
		self.filters.end_date = getdate(self.filters.selected_date[1] if self.filters.selected_date else nowdate())

	def run(self, args):
		party_naming_by = frappe.db.get_value(args.get("naming_by")[0], None, args.get("naming_by")[1])
		columns = self.get_columns(party_naming_by, args)
		data = self.get_data(party_naming_by, args)
		return columns, data, None

	def get_columns(self, party_naming_by, args):
		columns = [
			_("Posting Date") + ":Date:80",
			_("Customer") + ":Link/Customer:120",
			_("Location") + ":Link/Warehouse:120"
		]

		if party_naming_by == "Naming Series":
			columns += ["Customer Name::110"]

		columns += [
			_("Voucher Type") + "::110",
			_("Voucher No") + ":Dynamic Link/" + _("Voucher Type") + ":120",
			_("Related Docs") + "::160",
			_("Invoiced") + ":Currency/currency:100"
		]

		for mode_of_payment in self.get_mode_of_payment():
			columns.append(_(mode_of_payment) + ":Currency/currency:100")

		columns += [
			_("Total Paid") + ":Currency/currency:100",
			_("Return") + ":Currency/currency:100",
			_("Outstanding") + ":Currency/currency:100",
			_("Contra") + ":Currency/currency:100",
			_("Discount") + ":Currency/currency:100",
			_("Taxes & Charges") + ":Currency/currency:100",
			_("Currency") + ":Link/Currency:70",
			_("Owner") + ":Link/User:150",
			_("Sales Person") + "::160"
		]

		return columns

	def get_mode_of_payment(self):
		if not hasattr(self, "payment_mode"):
			self.payment_mode = [d.name for d in frappe.get_all('Mode of Payment')]
			self.payment_mode += ["Other"]
		return self.payment_mode

	def get_data(self, party_naming_by, args):
		from erpnext.accounts.utils import get_currency_precision
		currency_precision = get_currency_precision() or 2
		debit = "debit"

		if not self.filters.get("company"):
			self.filters["company"] = frappe.db.get_single_value('Global Defaults', 'default_company')

		voucher_no_list = []
		for gle in self.get_entries_between(self.filters.start_date, self.filters.end_date):
			if self.is_receivable(gle, debit):
				voucher_no_list.append(gle.voucher_no)
		sales_person_map = self.get_sales_person(voucher_no_list)

		data = []
		for gle in self.get_entries_between(self.filters.start_date, self.filters.end_date):
			if self.is_receivable(gle, debit):
				outstanding_amount, return_amount,\
				payment_mode, contra_amount, related_docs = self.get_detail_info(voucher_no_list, gle,
																			  self.filters.end_date, debit, currency_precision)
				row = [gle.posting_date, gle.party]

				# customer
				if party_naming_by == "Naming Series":
					row += [gle.customer_name]

				# location, voucher_type and voucher_no
				row += [gle.location, gle.voucher_type, gle.voucher_no, ', '.join(related_docs)]

				# invoiced amounts
				invoiced_amount = gle.get(debit) if (gle.get(debit) > 0) else 0

				row += [
					invoiced_amount
				]
				paid_amt = 0.0
				# payment mode amounts
				for mode_of_payment in self.get_mode_of_payment():
					paid_amt += payment_mode[mode_of_payment]
					row.append(payment_mode[mode_of_payment])

				row += [
					paid_amt,
					return_amount,
					outstanding_amount,
					contra_amount,
					# Only sales invoice has discount and taxes so we have to check
					gle.discount_amount if gle.discount_amount else 0,
					gle.total_taxes_and_charges if gle.total_taxes_and_charges else 0,
					gle.account_currency,
					gle.owner,
					sales_person_map[gle.voucher_no] if gle.voucher_no in sales_person_map else ""
				]

				data.append(row)
		return data

	def get_sales_person(self, voucher_no_list):
		format_voucher_no = ','.join(['%s'] * len(voucher_no_list))
		sales_person = frappe.db.sql("select parent, group_concat(sales_person separator ', ') as sales_person"
									 " from `tabSales Team` where parent in (%s) group by parent" % format_voucher_no,
							 voucher_no_list, as_dict=True)
		sales_person_map = {}
		for sp in sales_person:
			sales_person_map[sp.parent] = sp.sales_person
		return sales_person_map

	def get_entries_between(self, start_date, end_date):
			return (e for e in self.get_gl_entries() if start_date <= getdate(e.posting_date) <= end_date)

	def is_receivable(self, gle, dr_or_cr):
		return (
			# advance payment from payment entry only
			# it is also possible to pay from journal entry but we only consider payment entry in our case
			(not gle.against_voucher and gle.voucher_type == "Payment Entry") or

			# against sales order/purchase order
			(gle.against_voucher_type in ["Sales Order"]) or

			# sales invoice/purchase invoice
			# when against_voucher is equal to voucher_no, it means the invoice is original entry
			(gle.voucher_type == "Sales Invoice" and gle.against_voucher == gle.voucher_no and gle.get(dr_or_cr) > 0)

			# entries adjusted with future vouchers
			# TODO: Check the use case for future vouchers
			# ((gle.against_voucher_type, gle.against_voucher) in future_vouchers)
		)

	def get_detail_info(self, voucher_no_list, gle, end_date, dr_or_cr, currency_precision):
		payment_amount, return_amount, outstanding_amount, contra_amount = 0.0, 0.0, 0.0, 0.0
		related_docs = []
		reverse_dr_or_cr = "credit" if dr_or_cr=="debit" else "debit"
		payment_mode = {}
		for mode_of_payment in self.get_mode_of_payment():
			payment_mode[mode_of_payment] = 0.0

		# In some cases where payment entry is made against sales order as advance payment
		if gle.against_voucher != gle.voucher_no and gle.against_voucher is not None:
			related_docs.append(gle.against_voucher)

		# if an entry itself has mode_of_payment we include it in the calculation
		if gle.mode_of_payment:
			payment_mode[gle.mode_of_payment] += flt(gle.get(reverse_dr_or_cr))

		for e in self.get_related_gl_entries(gle.party, gle.voucher_type, gle.voucher_no, voucher_no_list):
			# TODO: Check the use case for due_date
			if getdate(e.posting_date) <= end_date and (not gle.due_date or getdate(e.due_date) == getdate(gle.due_date)) and e.name != gle.name:
				related_docs.append(e.voucher_no)
				amount = flt(e.get(reverse_dr_or_cr)) - flt(e.get(dr_or_cr))

				if not e.is_return:
					if amount > 0:
						# Positive amount means we receive either payment or return
						# TODO: Make another payment mode for credit note instead of using other
						if e.mode_of_payment is None:
							payment_mode["Other"] += amount
						else:
							payment_mode[e.mode_of_payment] += amount
						payment_amount += amount
					else:
						# Negative amount means we either return back the money or created a credit note
						contra_amount += -amount
				else:
					return_amount += amount


		# Only sales invoice has outstanding and return amount
		if gle.voucher_type == 'Sales Invoice':
			outstanding_amount = flt((flt(gle.get(dr_or_cr)) - flt(gle.get(reverse_dr_or_cr))
				- payment_amount - return_amount + contra_amount), currency_precision)
			return_amount = flt(return_amount, currency_precision)
		print(related_docs)
		return outstanding_amount, return_amount, payment_mode, contra_amount, related_docs

	def get_gl_entries(self):
		if not hasattr(self, "gl_entries"):
			conditions, values = self.prepare_conditions()

			if self.filters.get(scrub("Customer")):
				select_fields = "sum(gle.debit_in_account_currency) as debit, sum(gle.credit_in_account_currency) as credit"
			else:
				select_fields = "sum(gle.debit) as debit, sum(gle.credit) as credit"

			self.gl_entries = frappe.db.sql("""select gle.name, gle.posting_date, gle.account, gle.party_type, gle.party, 
				gle.voucher_type, gle.voucher_no, gle.against_voucher_type, gle.against_voucher, gle.due_date, gle.owner,
				gle.account_currency, gle.remarks, si.discount_amount, si.total_taxes_and_charges, si.is_return,
				(case when gle.voucher_type = 'Sales Invoice' then sip.mode_of_payment
				when gle.voucher_type = 'Payment Entry' then pe.mode_of_payment
				else NULL end) as mode_of_payment,
				(case when gle.voucher_type = 'Sales Invoice' then si.iverifii_doc_location
				when gle.voucher_type = 'Payment Entry' then pe.iverifii_doc_location
				else je.iverifii_doc_location end) as location, si.is_return, c.customer_name, {0}
				from `tabGL Entry` gle
				left join `tabSales Invoice Payment` sip
				  	on gle.voucher_no = sip.parent
				left join `tabPayment Entry` pe
					on gle.voucher_no = pe.name
				left join `tabSales Invoice` si
					on gle.voucher_no = si.name
				left join `tabJournal Entry` je
					on gle.voucher_no = je.name
				left join `tabCustomer` c
					on gle.party = c.name
				where gle.docstatus < 2 and gle.party_type = %s and (gle.party is not null and gle.party != '') 
				and ((gle.voucher_no = gle.against_voucher or gle.against_voucher IS NULL 
				or gle.against_voucher_type = "Sales Order") and gle.posting_date between %s and %s) {1}
				group by gle.voucher_type, gle.voucher_no, gle.against_voucher_type, gle.against_voucher, gle.party
				order by gle.posting_date, gle.party"""
				.format(select_fields, conditions), values, as_dict=True)

		return self.gl_entries

	def get_related_gl_entries(self, party, against_voucher_type, against_voucher, voucher_no_list):
		if not hasattr(self, "related_gl_entries"):
			strenddate = self.filters.end_date.strftime(DATE_FORMAT)

			format_voucher_no = ','.join(['%s'] * len(voucher_no_list))

			if self.filters.get(scrub("Customer")):
				select_fields = "sum(gle.debit_in_account_currency) as debit, sum(gle.credit_in_account_currency) as credit"
			else:
				select_fields = "sum(gle.debit) as debit, sum(gle.credit) as credit"

			values = [strenddate] + voucher_no_list

			sqlstring = """select gle.name, gle.posting_date, gle.account, gle.party_type, gle.party, 
				gle.voucher_type, gle.voucher_no, gle.against_voucher_type, gle.against_voucher, gle.due_date, gle.account_currency, 
				(case when gle.voucher_type = 'Sales Invoice' then sip.mode_of_payment
				when gle.voucher_type = 'Payment Entry' then pe.mode_of_payment
				else NULL end) as mode_of_payment, si.is_return, {0}
				from `tabGL Entry` gle
				left join `tabSales Invoice Payment` sip
				  	on gle.voucher_no = sip.parent
				left join `tabPayment Entry` pe
					on gle.voucher_no = pe.name
				left join `tabSales Invoice` si
					on gle.voucher_no = si.name
				where gle.posting_date <= %%s and gle.against_voucher in (%s)
				group by gle.voucher_type, gle.voucher_no"""\
				.format(select_fields)

			related_gl_entries = frappe.db.sql(sqlstring % (format_voucher_no), values, as_dict=True)

			self.related_gl_entries = {}
			for gle in related_gl_entries:
				if gle.against_voucher_type and gle.against_voucher:
					self.related_gl_entries.setdefault(gle.party, {}) \
						.setdefault(gle.against_voucher_type, {}) \
						.setdefault(gle.against_voucher, []) \
						.append(gle)
		return self.related_gl_entries.get(party, {})\
			.get(against_voucher_type, {})\
			.get(against_voucher, [])

	def prepare_conditions(self):
		conditions = [""]
		strstartdate = self.filters.start_date.strftime(DATE_FORMAT)
		strenddate = self.filters.end_date.strftime(DATE_FORMAT)
		values = ["Customer", strstartdate, strenddate]

		party_type_field = scrub("Customer")

		if self.filters.company:
			conditions.append("gle.company=%s")
			values.append(self.filters.company)

		if self.filters.get(party_type_field):
			conditions.append("gle.party=%s")
			values.append(self.filters.get(party_type_field))

		if self.filters.owner:
			conditions.append("gle.owner=%s")
			values.append(self.filters.owner)

		# TODO: find a way to support tree
		if self.filters.location:
			conditions.append("(je.iverifii_doc_location=%s or pe.iverifii_doc_location=%s or si.iverifii_doc_location=%s)")
			values += [self.filters.location, self.filters.location, self.filters.location]

		if self.filters.get("customer_group"):
			lft, rgt = frappe.db.get_value("Customer Group",
										   self.filters.get("customer_group"), ["lft", "rgt"])

			conditions.append("""gle.party in (select name from tabCustomer
						where exists(select name from `tabCustomer Group` where lft >= {0} and rgt <= {1}
							and name=tabCustomer.customer_group))""".format(lft, rgt))


		return " and ".join(conditions), values

def execute(filters=None):
	args = {
		"party_type": "Customer",
		"naming_by": ["Selling Settings", "cust_master_name"],
	}
	return IverifiiDailySales(filters).run(args)
