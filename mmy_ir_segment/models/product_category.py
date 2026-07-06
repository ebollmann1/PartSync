# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import itertools

class IRSegment(models.Model):
    _name = "ir.segment"
    
    name = fields.Char('Name')

class ProductAttribute(models.Model):
    _inherit = 'product.attribute'
    
    # i_r_segment = fields.Selection([
    #     ('1', '1'),
    #     ('2', '2'),
    #     ('3', '3'),
    #     ('4', '4'),
    #     ('5', '5'),
    #     ('6', '6'),
    # ], string="I/R Segment")
    ir_segment = fields.Integer(string="I/R Segment")

class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'
    
    i_r_segment_value = fields.Many2one('ir.segment', string="I/R Segment Value")

class ProductCategory(models.Model):
    _inherit = "product.category"
    
    internal_ref_rules = fields.Selection(selection_add=[
        ('attribute_defined_ir', 'Attribute Defined I/R')
    ], ondelete={'attribute_defined_ir': 'cascade'})

class ProductTemplate(models.Model):
    _inherit = "product.template"
    
    def _create_variant_ids(self):
        res = super(ProductTemplate, self)._create_variant_ids()
        for rec in self:
            if rec.categ_id.internal_ref_rules == 'attribute_defined_ir':
                attribute_dict = {}
                attribute_ids_list = []
                attribute_ids_list += rec.valid_product_template_attribute_line_ids.filtered(
                    lambda ptal: ptal.attribute_id.create_variant == 'no_variant'
                ).mapped('attribute_id').ids
                attribute_ids_list += rec.product_variant_ids.mapped('product_template_attribute_value_ids').mapped('attribute_id').ids
                # attribute_ids_list = Total attribute list
                sorted_attribute_ids = sorted(self.env['product.attribute'].browse(attribute_ids_list), key=lambda a: a.ir_segment)
                if sorted_attribute_ids:
                    # attribute_dict = create sorted attribute blank dict
                    for attribute in sorted_attribute_ids:
                        attribute_dict[attribute.id] = False

                    ptav_ids = rec.valid_product_template_attribute_line_ids.filtered(
                        lambda ptal: ptal.attribute_id.create_variant == 'no_variant'
                    ).mapped('value_ids').filtered(lambda l: l.i_r_segment_value.name)
                    for ptav in ptav_ids:
                        if ptav.attribute_id.id in attribute_dict and attribute_dict[ptav.attribute_id.id]:
                            attribute_dict[ptav.attribute_id.id] += '-' + ptav.i_r_segment_value.name
                        else:
                            attribute_dict[ptav.attribute_id.id] = ptav.i_r_segment_value.name

                    for product in rec.product_variant_ids:
                        ptav_dict = attribute_dict.copy()
                        for com in product.product_template_attribute_value_ids:
                            ptav_dict[com.attribute_id.id] = com.product_attribute_value_id.i_r_segment_value.name

                        default_code = '-'.join(str(v) for v in ptav_dict.values() if v)
                        if default_code:
                            product.with_context(skip_default_code=True).write({
                                'default_code': default_code
                            })
        return res