# -*- coding: utf-8 -*-

from odoo import api, fields, models,_


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def compute_total_fitment(self):
        """
        Compute total fitment for a product by aggregating all fitments from related CPMs
        """
        for rec in self:
            CPM_ids = rec.customer_product_master_ids
            fitment_ids = self.env['fitment.master']
            for CPM_id in CPM_ids.filtered(lambda c: c.fitment_ids):
                fitment_ids |= CPM_id.fitment_ids
            rec.total_fitment = len(fitment_ids)
            rec.fitment_ids = fitment_ids

    product_height = fields.Char(string="Height (Inch)")
    product_width = fields.Char(string="Width (Inch)")
    product_length = fields.Char(string="Length (Inch)")
    total_fitment = fields.Integer(string='Total Fitment', compute='compute_total_fitment', )
    fitment_ids = fields.Many2many('fitment.master', compute='compute_total_fitment')
    customer_product_master_ids = fields.One2many('customer.product.master', 'product_id')

    @api.onchange('product_height', 'product_width', 'product_length')
    def onchange_height_width_length(self):
        """
        Compute volume from height/width/length
        """
        if self.product_height or self.product_width or self.product_length:
            self.volume = float(self.product_width or 0) * float(self.product_height or 0) * float(self.product_length or 0)

    def action_show_fitment_data(self):
        """
        Open action to show related fitment records
        """
        CPM_ids = self.customer_product_master_ids
        action = self.env["ir.actions.actions"]._for_xml_id("project_cars_enhancement.customer_product_master_action")
        action['domain'] = [('id', 'in', CPM_ids.ids)]
        # Default set
        action['context'] = {
            'default_list_ids': self.ids,
            'default_product_template_id': self.product_tmpl_id.id,
            'default_product_id': self.id
        }
        
        return action
    
    def sync_fitment_to_variant(self):
        """
        Sync fitments from one variant to all variants if missing
        """
        variant_ids = self.product_tmpl_id.product_variant_ids
        customer_product_master_id = self.env['customer.product.master'].search([
            ('product_id','in', variant_ids.ids),
            ('fitment_ids', '!=', False)
        ],limit=1)
        fitment_dict = {}
        fitment_data = self.env['customer.product.master'].search_read([('product_id', '!=', False)], fields=['product_id', 'id'])
        for record in fitment_data:
            if record.get('product_id') and record.get('product_id')[0] not in fitment_dict:
                fitment_dict[record.get('product_id')[0]] = record.get('id')
        if customer_product_master_id:
            for product in variant_ids:
                if product.id not in fitment_dict:
                    new_fitment = customer_product_master_id.copy(
                        default={
                            'product_id': product.id,
                            'cpm_validation_id': customer_product_master_id.cpm_validation_id.id

                        }
                    )
                    new_fitment.product_id = product.id
                    new_fitment.cpm_validation_id = customer_product_master_id.cpm_validation_id.id


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def compute_total_fitment_template(self):
        """
        Compute total fitments for a product template aggregating all variant fitments
        """
        for rec in self:
            product_ids = rec.product_variant_ids
            CPM_ids = product_ids.mapped('customer_product_master_ids')
            fitment_ids = self.env['fitment.master']
            for CPM_id in CPM_ids.filtered(lambda c: c.fitment_ids):
                fitment_ids |= CPM_id.fitment_ids
            rec.total_fitment_template = len(fitment_ids)
            rec.fitment_ids = fitment_ids

    extend_product_description = fields.Text(string="Extended Product Description")
    additional_product_info = fields.Text(string="Additional Product Info")
    product_height = fields.Char(string="Height (Inch)")
    product_width = fields.Char(string="Width (Inch)")
    product_length = fields.Char(string="Length (Inch)")
    total_fitment_template = fields.Integer(string='Total Fitment For Template', compute='compute_total_fitment_template')
    fitment_ids = fields.Many2many('fitment.master', compute='compute_total_fitment_template')

    @api.onchange('product_height', 'product_width', 'product_length')
    def onchange_height_width_length(self):
        """
        Compute volume based on dimensions like width,height and length
        """
        if self.product_height or self.product_width or self.product_length:
            self.volume = float(self.product_width or 0) * float(self.product_height or 0) * float(self.product_length or 0)

    def action_show_fitment_data_template(self):
        """
        Show Customer Product Information records related to this template
        """
        product_ids = self.product_variant_ids
        CPM_ids = product_ids.mapped('customer_product_master_ids')
        action = self.env["ir.actions.actions"]._for_xml_id("project_cars_enhancement.customer_product_master_action")
        action['domain'] = [('id', 'in', CPM_ids.ids)]
        # Default set
        action['context'] = {'default_list_ids': self.ids, 'default_product_template_id':self.id}
        if len(self.product_variant_ids) >= 1:
            action['context'].update({
                'default_product_id': self.product_variant_ids[0].id
            })
        return action

    def sync_fitment_to_variant(self):
        """
        Sync fitments from template to its variants if missing
        """
        variant_ids = self.product_variant_ids
        customer_product_master_id = self.env['customer.product.master'].search([
            ('product_id','in', variant_ids.ids),
            ('fitment_ids', '!=', False)
        ],limit=1)
        fitment_dict = {}
        fitment_data = self.env['customer.product.master'].search_read([('product_id', '!=', False)], fields=['product_id', 'id'])
        for record in fitment_data:
            if record.get('product_id') and record.get('product_id')[0] not in fitment_dict:
                fitment_dict[record.get('product_id')[0]] = record.get('id')

        if customer_product_master_id:
            for product in variant_ids:
                if product.id not in fitment_dict:
                    new_fitment = customer_product_master_id.copy(
                        default={
                            'product_id': product.id,
                            'cpm_validation_id': customer_product_master_id.cpm_validation_id.id

                        }
                    )
                    new_fitment.product_id = product.id
                    new_fitment.cpm_validation_id = customer_product_master_id.cpm_validation_id.id

    def _get_ppf(self):
        """
        Get system parameter for product filtering
        """
        return self.env['ir.config_parameter'].sudo().get_param('mmy_config.partsync_product_filtering')

    def _get_pef(self):
        """
        Get system parameter for eCommerce filtering
        """
        return self.env['ir.config_parameter'].sudo().get_param('mmy_config.partsync_eCommerce_filtering')
