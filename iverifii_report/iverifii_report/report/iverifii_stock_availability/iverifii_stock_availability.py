# Copyright (c) 2013, Iverifii and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe
from frappe import _
from frappe.utils import flt

ACTUAL = "_actual"
PROJECTED = "_projected"
TOTAL = "Total"

class IverifiiStockAvailability(object):
	def __init__(self, filters=None):
		self.filters = frappe._dict(filters or {})

	def run(self):
		columns = self.get_columns()
		data = self.get_data()
		return columns, data

	def get_columns(self):
		columns = [
			_("Item") + ":Link/Item:150",
			_("Description") + "::300"
		]

		for warehouse in self.get_warehouse():
			columns.append(_(warehouse) + "::120")

		return columns

	def get_warehouse(self):
		if not hasattr(self, "warehouse"):
			filters = { "is_group": 0 }
			if self.filters.get("company"):
				filters["company"] = self.filters.get("company")

			self.warehouse = [w.name for w in frappe.get_all('Warehouse', fields = ["name"], filters = filters)]
			self.warehouse += [TOTAL]
		return self.warehouse

	def get_data(self):
		data = {}
		for stock in self.get_total_stock():
			fltactualqty = flt(stock.actual_qty)
			fltprojectedqty = flt(stock.projected_qty)
			actualqty = stock.warehouse + ACTUAL
			projectedqty = stock.warehouse + PROJECTED
			totalactualqty = TOTAL + ACTUAL
			totalprojectedqty = TOTAL + PROJECTED
			single_data = {}
			if stock.item_code in data:
				single_data = data[stock.item_code]
			else:
				single_data["item_code"] = stock.item_code
				single_data["description"] = stock.description

				for warehouse in self.get_warehouse():
					actual = warehouse + ACTUAL
					projected = warehouse + PROJECTED
					single_data[actual] = 0.0
					single_data[projected] = 0.0

			single_data[actualqty] += fltactualqty
			single_data[projectedqty] += fltprojectedqty
			single_data[totalactualqty] += fltactualqty
			single_data[totalprojectedqty] += fltprojectedqty
			data[stock.item_code] = single_data

		list_data = []

		for key, value in data.items():
			row = [
				value['item_code'],
				value['description']
			]

			for warehouse in self.get_warehouse():
				row += [
					str(value[warehouse + ACTUAL]) + " (%s)" % str(value[warehouse + PROJECTED]),
				]

			list_data.append(row)

		return list_data

	def get_total_stock(self):
		conditions = ""

		if self.filters.get("company"):
			conditions += " AND warehouse.company = '%s'" % frappe.db.escape(self.filters.get("company"), percent=False)

		if self.filters.get("item_group"):
			ig_details = frappe.db.get_value("Item Group", self.filters.get("item_group"),
											 ["lft", "rgt"], as_dict=1)

			if ig_details:
				conditions += """ 
					and exists (select name from `tabItem Group` ig 
					where ig.lft >= %s and ig.rgt <= %s and item.item_group = ig.name)
				""" % (ig_details.lft, ig_details.rgt)

		if self.filters.get("item_code"):
			conditions += " and item.item_code = '%s'" % frappe.db.escape(self.filters.get("item_code"), percent=False)

		return frappe.db.sql("""
				SELECT
					ledger.warehouse,
					item.item_code,
					item.description,
					sum(ledger.actual_qty) as actual_qty,
					sum(ledger.projected_qty) as projected_qty
				FROM
					`tabBin` AS ledger
				INNER JOIN `tabItem` AS item
					ON ledger.item_code = item.item_code
				INNER JOIN `tabWarehouse` warehouse
					ON warehouse.name = ledger.warehouse
				WHERE
					actual_qty != 0 %s
				GROUP BY ledger.warehouse, item.item_code""" % conditions, as_dict=True)


def execute(filters=None):
	return IverifiiStockAvailability(filters).run()