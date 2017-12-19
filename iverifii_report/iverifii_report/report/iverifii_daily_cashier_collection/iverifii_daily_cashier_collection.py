# Copyright (c) 2013, Iverifii and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import getdate, nowdate, cstr

class IverifiiDailyCashierCollection(object):
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})
		self.filters.from_date = self.filters.selected_date[0] if self.filters.selected_date else nowdate()
		self.filters.to_date = self.filters.selected_date[1] if self.filters.selected_date else nowdate()

	def run(self):
		columns = self.get_columns()
		data = self.get_data()
		return columns, data

	def get_columns(self):
		columns = [
			_("Posting Date") + ":Date:80",
			_("Customer") + ":Link/Customer:120",
			_("Location") + ":Link/Warehouse:120"
		]

		columns += [
			_("Voucher Type") + "::110",
			_("Voucher No") + ":Dynamic Link/" + _("Voucher Type") + ":120"
		]

		for mode_of_payment in self.get_mode_of_payment():
			columns.append(_(mode_of_payment) + ":Currency/currency:100")

		columns += [
			_("Total Paid") + ":Currency/currency:100",
			_("Currency") + ":Link/Currency:70",
			_("Owner") + ":Link/User:150"
		]

		return columns

	def get_data(self):
		data = []

		for k, v in self.get_sales_invoice_payment().items():
			data.append(self.process_row(v))

		for k, v in self.get_payment_entry_payment().items():
			data.append(self.process_row(v))

		return data

	def get_conditions(self):
		conditions = ""
		if self.filters.get("company"): conditions += " a.company=%(company)s"
		if self.filters.get("owner"): conditions += " and a.owner = %(owner)s"
		if self.filters.get("location"): conditions += " and a.iverifii_doc_location = %(location)s"
		if self.filters.get("from_date"): conditions += " and a.posting_date >= %(from_date)s"
		if self.filters.get("to_date"): conditions += " and a.posting_date <= %(to_date)s"
		return conditions

	def process_row(self, v):
		row = [v.posting_date, v.customer, v.location, v.voucher_type, v.name]
		total_paid = 0
		for mode_of_payment in self.get_mode_of_payment():
			row.append(v[mode_of_payment])
			total_paid += v[mode_of_payment]
		row += [total_paid, v.currency, v.owner]
		return row

	def process_data(self, data, voucher_type):
		result = {}
		for d in data:
			if d.name in result:
				result[d.name][d.mode_of_payment] += d.base_amount
			else:
				for mode_of_payment in self.get_mode_of_payment():
					if d.mode_of_payment == mode_of_payment:
						d[mode_of_payment] = d.base_amount
					else:
						d[mode_of_payment] = 0.0
				d["voucher_type"] = voucher_type
				result[d.name] = d
		return result


	def get_mode_of_payment(self):
		if not hasattr(self, "payment_mode"):
			self.payment_mode = [d.name for d in frappe.get_all('Mode of Payment')]
			self.payment_mode += ["Other"]
		return self.payment_mode

	def get_sales_invoice_payment(self):
		conditions = self.get_conditions()
		sales_invoice = frappe.db.sql("""
	    		select
	    			a.name, a.iverifii_doc_location as location, a.posting_date, a.customer, a.owner, 
	    			b.base_amount, b.mode_of_payment, a.currency
	    		from `tabSales Invoice` a, `tabSales Invoice Payment` b
	    		where a.name = b.parent 
	    		and a.docstatus = 1
	    		and {conditions}
	    	""".format(conditions=conditions), self.filters, as_dict=1)

		return self.process_data(sales_invoice, "Sales Invoice")

	def get_payment_entry_payment(self):
		conditions = self.get_conditions()
		payment_entry = frappe.db.sql("""
	    	    		select
	    	    			name, iverifii_doc_location as location, posting_date, party as customer, owner, 
	    	    			base_received_amount as base_amount, mode_of_payment, paid_from_account_currency as currency
	    	    		from `tabPayment Entry` a
	    	    		where a.docstatus = 1
	    	    		and party_type = 'Customer'
	    	    		and payment_type = 'Receive'
	    	    		and {conditions}
	    	    	""".format(conditions=conditions), self.filters, as_dict=1)

		return self.process_data(payment_entry, "Payment Entry")

def execute(filters=None):
	return IverifiiDailyCashierCollection(filters).run()