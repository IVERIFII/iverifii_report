// Copyright (c) 2016, nchenbang@iverifii and contributors
// For license information, please see license.txt
/* eslint-disable */
frappe.query_reports["Iverifii Daily Sales"] = {
	"filters": [
		{
			"fieldname":"company",
			"label": __("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company")
		},
		{
			"fieldname":"customer",
			"label": __("Customer"),
			"fieldtype": "Link",
			"options": "Customer"
		},
		{
			"fieldname":"customer_group",
			"label": __("Customer Group"),
			"fieldtype": "Link",
			"options": "Customer Group"
		},
		{
			"fieldname":"location",
			"label": __("Location"),
			"fieldtype": "Link",
			"options": "Warehouse"
		},
		{
			"fieldname":"owner",
			"label": __("Owner"),
			"fieldtype": "Link",
			"options": "User"
		},
		{
			"fieldtype": "Break",
		},
		{
			"fieldname":"selected_date",
			"label": __("Selected Date"),
			"fieldtype": "Date Range",
			"reqd": true
		}
	]
}
