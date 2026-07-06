# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ProductCategory(models.Model):
    _inherit = "product.category"
    
    internal_ref_rules = fields.Selection([
        ('null', 'Null'),
        ('auto-generate', 'Auto Generate - No Prefix'),
        ('user-defined-prefix', 'User Defined Prefix')
    ],default='null', required=True, string="Internal Reference Rules")
    prefix_product_ref = fields.Char("Prefix")


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model_create_multi
    def create(self, vals_list):
        """
        Auto-generate internal reference (default_code) for products based on category settings.
        """
        for vals in vals_list:
            if vals.get('categ_id', False):
                categ_id = vals.get('categ_id')
                category = self.env['product.category'].browse(categ_id)
                if category.internal_ref_rules != 'null':

                    if vals.get('attribute_line_ids') and len(vals['attribute_line_ids']) > 0:
                        continue

                    if not categ_id:
                        raise ValidationError(_("You must select a product category to generate the internal reference."))

                    code = 'product.internal.ref.category'
                    new_code = self.env['ir.sequence'].next_by_code(code)
                    if category.internal_ref_rules == 'user-defined-prefix':
                        vals['default_code'] = f"{category.prefix_product_ref}{new_code}"
                    else:
                        vals['default_code'] = f"{new_code}"
        return super(ProductTemplate, self).create(vals_list)

    
    def write(self, vals):
        """
        Auto-generate internal reference for products missing default_code on update.
        """
        res = super(ProductTemplate, self).write(vals)
        if 'skip_default_code' not in self._context:
            for rec in self:
                if not rec.default_code and rec.categ_id:
                    if rec.categ_id.internal_ref_rules != 'null':
                        if rec.attribute_line_ids:
                            continue
                        if not rec.categ_id:
                            raise ValidationError(
                                _("You must select a product category to generate the internal reference."))

                        code = 'product.internal.ref.category'
                        new_code = self.env['ir.sequence'].next_by_code(code)
                        if rec.categ_id.internal_ref_rules == 'user-defined-prefix':
                            default_code = f"{rec.categ_id.prefix_product_ref}{new_code}"
                        else:
                            default_code = f"{new_code}"
                        rec.with_context(skip_default_code=True).write({'default_code': default_code})
        return res

    def generate_internal_reference(self):
        """
        Manually generate/regenerate internal reference for selected products.
        """
        for product in self:
            category = product.categ_id
            if not category:
                raise ValidationError(_("You must select a product category to generate the internal reference."))

            if category.internal_ref_rules != 'null':
                code = 'product.internal.ref.category'
                new_code = self.env['ir.sequence'].next_by_code(code)

                if category.internal_ref_rules == 'user-defined-prefix':
                    product.default_code = f"{category.prefix_product_ref}{new_code}"
                else:
                    product.default_code = new_code

class ProductProduct(models.Model):
    _inherit = 'product.product'
    
    def write(self, vals):
        """
        Auto-generate internal reference (default_code) for products based on category settings.
        """
        res = super(ProductProduct, self).write(vals)
        if 'skip_default_code' not in self._context:
            for rec in self:
                if not rec.default_code and rec.categ_id:
                    if rec.categ_id.internal_ref_rules != 'null':
                        if not rec.categ_id:
                            raise ValidationError(
                                _("You must select a product category to generate the internal reference."))

                        code = 'product.internal.ref.category'
                        new_code = self.env['ir.sequence'].next_by_code(code)
                        if rec.categ_id.internal_ref_rules == 'user-defined-prefix':
                            default_code = f"{rec.categ_id.prefix_product_ref}{new_code}"
                        else:
                            default_code = f"{new_code}"
                        rec.with_context(skip_default_code=True).write({'default_code': default_code})
                        rec.product_tmpl_id.with_context(skip_default_code=True).write({'default_code': default_code})
        return res
