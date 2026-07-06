# -*- coding: utf-8 -*-

from odoo import fields, models, api,_
from odoo.exceptions import ValidationError


class VehiclePlatform(models.Model):
    _name = "vehicle.platform"
    _description = 'Vehicle Platform'

    name = fields.Char(string="Platform")

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        "You cannot have two Vehicle Platform with the same name!"
    )


class year(models.Model):
    _name = "fitment.year"
    _description = 'Year'

    name = fields.Char(string="Year")

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        "You cannot have two Year with the same name!"
    )

class make(models.Model):
    _name = "fitment.make"
    _description = 'Make'

    name = fields.Char(string="Make")

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        "You cannot have two Make with the same name!"
    )

class model(models.Model):
    _name = "fitment.model"
    _description = 'Model'

    name = fields.Char(string="Model")

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        "You cannot have two Model with the same name!"
    )

class submodel(models.Model):
    _name = "fitment.submodel"
    _description = 'Submodel'

    name = fields.Char(string="Submodel")

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        "You cannot have two Submodel with the same name!"
    )

class RearWheels(models.Model):
    _name = "fitment.rear.wheels"
    _description = 'Wheel Configuration'

    name = fields.Char(string="Wheel Configuration")

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        "You cannot have two Wheel Configuration with the same name!"
    )


class FitmentMaster(models.Model):
    _name = "fitment.master"
    _description = 'Fitment Master'
    _rec_name = 'make_id'

    year_id = fields.Many2one(comodel_name='fitment.year', string="Year")
    make_id = fields.Many2one(comodel_name='fitment.make', string="Make")
    model_id = fields.Many2one(comodel_name='fitment.model', string="Model")
    submodel_id = fields.Many2one(comodel_name='fitment.submodel', string="Submodel")
    rear_wheels_id = fields.Many2one(comodel_name='fitment.rear.wheels', string="Wheel Configuration")
    vehicle_platform_id = fields.Many2one(comodel_name='vehicle.platform', string="Platform")
    generation = fields.Char(string="Drive")
    fitment_class = fields.Char(string="Class")

    def name_get(self):
        """
        Compute the display name for each fitment.master record
        by concatenating Year, Make, Model, Submodel, and Rear Wheels.
        Example: "2022, Toyota, Corolla, Sedan, 4 Wheels"
        """
        res = []
        for fitment_id in self:
            name = str(fitment_id.year_id.name) if fitment_id.year_id else ''
            if fitment_id.make_id:
                name = name + ', ' + fitment_id.make_id.name
            if fitment_id.model_id:
                name = name + ', ' + fitment_id.model_id.name
            if fitment_id.submodel_id:
                name = name + ', ' + fitment_id.submodel_id.name
            if fitment_id.rear_wheels_id:
                name = name + ', ' + fitment_id.rear_wheels_id.name
            res += [(fitment_id.id, name)]
        return res

    _unique_year_make_model_submodel = models.Constraint(
        'UNIQUE(year_id, make_id, model_id, submodel_id, rear_wheels_id, generation)',
        'Year, Make, Model, Submodel, Wheel Configuration and generation value not allow duplicate!'
    )


class CustomerProductFitmentMaster(models.Model):
    _name = "customer.product.master"
    _description = 'Customer Product Master'
    _rec_name = 'brand_customer_name'


    brand_customer_name = fields.Char(string="Brand/Customer Name")
    cpm_validation_id = fields.Many2one(
        comodel_name='cpm.validation', copy=False, string="Brand/Customer Code", required=False,
        domain=lambda self: [('id', 'in', [cpm_id.id for cpm_id in self.env.company.cpm_validation_ids])])
    product_id = fields.Many2one('product.product', string="Product", copy=False, required=False)
    product_template_id = fields.Many2one('product.template', related="product_id.product_tmpl_id", string="Product Template", copy=False)
    # product_template_id = fields.Many2one('product.template', related=False, string="Product Template", copy=False, readonly=True, default=_get_default_product_template_id)
    fitment_ids = fields.Many2many(
        comodel_name='fitment.master', relation='cust_prod_master_fitment_obj',
        column1='cust_pro_master_id', column2='fitment_id', string="Fitments")
    part_terminology = fields.Integer(string="PartTerminologyID")
    company_id = fields.Many2one(related="product_id.company_id", store=True)

    _unique_cpm_product = models.Constraint(
        'UNIQUE(cpm_validation_id, product_id)',
        'Brand ID/Customer Code and Product value not allow duplicate!'
    )


    @api.onchange('cpm_validation_id')
    def _onchange_cpm_validation_id(self):
        """
        update 'brand_customer_name' when 'cpm_validation_id' is changed in the form
        """
        if self.cpm_validation_id:
            # Set brand_customer_name to the selected validation record's name
            self.brand_customer_name = self.cpm_validation_id and self.cpm_validation_id.name or False

    @api.model_create_multi
    def create(self, vals_list):
        """
        Auto fill 'brand_customer_name' for new records based on 'cpm_validation_id'
        """
        master_ids = super(CustomerProductFitmentMaster, self).create(vals_list)
        for rec in master_ids.filtered(lambda x: x.cpm_validation_id):
            rec.brand_customer_name = rec.cpm_validation_id.name
        return master_ids

    def write(self, vals):
        """
        update 'brand_customer_name' if 'cpm_validation_id' changes
        """
        res = super(CustomerProductFitmentMaster, self).write(vals)
        if self and self.cpm_validation_id and self.cpm_validation_id.name != self.brand_customer_name:
            self.brand_customer_name = self.cpm_validation_id.name
        return res
