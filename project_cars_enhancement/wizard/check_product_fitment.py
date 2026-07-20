# -*- coding: utf-8 -*-

from odoo import api, fields, models

class CheckProductFitment(models.TransientModel):
    _name = 'check.product.fitment'
    
    line_ids = fields.One2many('check.product.fitment.line', 'check_fitment_id')
    
class CheckProductFitmentLine(models.TransientModel):
    _name = 'check.product.fitment.line'
    
    check_fitment_id = fields.Many2one('check.product.fitment')
    old_product_id = fields.Many2one('product.product', string='Old Product')
    new_product_id = fields.Many2one('product.product', string='New Product')
    customer_master_id = fields.Many2one('customer.product.master')