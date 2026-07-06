# -*- coding: utf-8 -*-

from odoo import fields, api, models, _


class ProductAttribute(models.Model):
    _inherit = 'product.attribute'

    attribute_visibility = fields.Selection([
        ('visible', 'Visible'),
        ('hidden', 'Hidden')], default='visible', string="Attribute Info Display")

    show_attribute_visibility = fields.Boolean(
        compute='_compute_show_attribute_visibility'
    )

    def _compute_show_attribute_visibility(self):
        """
        Compute whether the attribute visibility should be shown based on system parameter
        """
        partsync_eCommerce_filtering = self.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_eCommerce_filtering')
        for rec in self:
            rec.show_attribute_visibility = partsync_eCommerce_filtering

    @api.onchange('attribute_visibility')
    def onchange_attribute_visibility(self):
        """
        warn user if trying to set 'hidden' visibility while variant creation is 'always' or 'dynamic'
        """
        if self.attribute_visibility == 'hidden':
            if self.create_variant == 'always' or self.create_variant == 'dynamic':
                return {
                    'warning': {
                        'title': _('Attribute Info Display.'),
                        'message': _(
                            "When Varient Creation mode is Instantly or Dynamically, then you can not sent hidden into Attribute Info Display.")
                    }
                }

    @api.model_create_multi
    def create(self, vals_list):
        """
        automatically correct invalid attribute_visibility when creating records
        """
        attribute_ids = super(ProductAttribute, self).create(vals_list)
        for attribute in attribute_ids.filtered(
            lambda a: a.attribute_visibility == 'hidden' and (a.create_variant == 'always' or a.create_variant == 'dynamic')
        ):
            attribute.attribute_visibility = 'visible'
        return attribute_ids

    def write(self, vals):
        """
        validate and correct attribute_visibility on updates
        """
        # Handle updates to create_variant when attribute_visibility is hidden
        if vals.get('create_variant', False) and vals.get('create_variant', '') in ['always', 'dynamic']:
            if self.attribute_visibility == 'hidden' and vals.get('attribute_visibility') != 'hidden':
                self.attribute_visibility = 'visible'

        # Handle updates to attribute_visibility when create_variant is always/dynamic
        if vals.get('attribute_visibility', '') == 'hidden':
            if self.create_variant in ['always', 'dynamic'] and vals.get('create_variant', '') != 'no_variant':
                self.attribute_visibility = 'visible'
                return {
                    'warning': {
                        'title': _('Attribute Info Display.'),
                        'message': _(
                            "When Varient Creation mode is Instantly or Dynamically, then you can not sent hidden into Attribute Info Display.")
                    }
                }
        return super(ProductAttribute, self).write(vals)


class ProductTemplateAttributeLine(models.Model):
    _inherit = 'product.template.attribute.line'
    
    def _update_product_template_attribute_values(self):
        """
        Extend the standard ProductTemplateAttributeLine method to:
        1. Copy the latest Customer Product Master (CPM) fitment mapping
           to new product variants.
        2. Ensure CPM records without a product_id are removed.
        """
        product_fitment_mapping = self.env['customer.product.master'].search([
            ('product_template_id', '=', self.product_tmpl_id.id)
        ], limit=1, order="id DESC")
        res = super(ProductTemplateAttributeLine, self)._update_product_template_attribute_values()
        product_list_ids = self.env['customer.product.master'].search([
            ('product_template_id', '=', self.product_tmpl_id.id),
            ('product_id', '!=', False)
        ]).mapped('product_id').ids
        if product_fitment_mapping:
            for product in self.product_tmpl_id.product_variant_ids:
                if product.id not in product_list_ids:
                    new_fitment_mapping = product_fitment_mapping.copy()
                    new_fitment_mapping.product_id = product.id
                    new_fitment_mapping.product_template_id = self.product_tmpl_id.id
                    new_fitment_mapping.cpm_validation_id = product_fitment_mapping.cpm_validation_id.id

            if product_fitment_mapping and not product_fitment_mapping.product_id:
                product_fitment_mapping.unlink()

        self.env['customer.product.master'].search([
            ('product_template_id', '=', self.product_tmpl_id.id),
            ('product_id', '=', False)
        ]).unlink()

        return res