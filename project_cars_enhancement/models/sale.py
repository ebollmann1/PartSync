# -*- coding: utf-8 -*-

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    vehicle_info_ids = fields.One2many(related="partner_id.vehicle_info_ids", string="Vehicle Information")

    show_vehicle_page = fields.Boolean(
        compute='_compute_show_vehicle_page'
    )

    def _compute_show_vehicle_page(self):
        """
        Compute whether the Vehicle page should be visible based on
        the system parameter 'mmy_config.partsync_customer_vehicle'.

        The field 'show_vehicle_page' will be True if the parameter is set,
        otherwise False.
        """
        partsync_customer_vehicle = self.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_customer_vehicle')
        for rec in self:
            rec.show_vehicle_page = partsync_customer_vehicle