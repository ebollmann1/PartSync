# -*- coding: utf-8 -*-

from odoo import fields, models, api


class VehicleInformation(models.Model):
    _name = "vehicle.information"
    _description = 'Vehicle Information'

    # Custom display name for vehicles combining make and VIN number
    @api.depends('make', 'vin_number')
    def name_get(self):
        result = []
        for vehicle_id in self:
            name = vehicle_id.make
            if vehicle_id.vin_number:
                name += '(' + vehicle_id.vin_number + ')'
            result.append((vehicle_id.id, name))
        return result


    # Return unique list of all makes from fitment.master for selection fields
    @api.model
    def get_make_value(self):
        fitment_ids = self.env['fitment.master'].sudo().search([])
        make_list = []
        make_data = []
        for fitment_id in fitment_ids:
            if fitment_id.make_id and fitment_id.make_id.id not in make_list:
                make_data.append((fitment_id.make_id.name, fitment_id.make_id.name))
                make_list.append(fitment_id.make_id.id)
        make_data.sort()
        return make_data

    # Return unique list of all models from fitment.master for selection fields
    @api.model
    def get_model_value(self):
        fitment_ids = self.env['fitment.master'].sudo().search([])
        model_list = []
        model_data = []
        for fitment_id in fitment_ids:
            if fitment_id.model_id and fitment_id.model_id.id not in model_list:
                model_data.append((fitment_id.model_id.name, fitment_id.model_id.name))
                model_list.append(fitment_id.model_id.id)
        model_data.sort()
        return model_data

    # Return unique list of all years from fitment.master for selection fields
    @api.model
    def get_year_value(self):
        fitment_ids = self.env['fitment.master'].sudo().search([])
        year_list = []
        year_data = []
        for fitment_id in fitment_ids:
            if fitment_id.year_id and fitment_id.year_id.id not in year_list:
                year_data.append((fitment_id.year_id.name, fitment_id.year_id.name))
                year_list.append(fitment_id.year_id.id)
        year_data.sort()
        return year_data

    # Return unique list of all submodels from fitment.master for selection fields
    @api.model
    def get_submodel_value(self):
        fitment_ids = self.env['fitment.master'].sudo().search([])
        submodel_list = []
        submodel_data = []
        for fitment_id in fitment_ids:
            if fitment_id.submodel_id and fitment_id.submodel_id.id not in submodel_list:
                submodel_data.append((fitment_id.submodel_id.name, fitment_id.submodel_id.name))
                submodel_list.append(fitment_id.submodel_id.id)
        submodel_data.sort()
        return submodel_data

    # Return unique list of all rear wheel configurations from fitment.master for selection fields
    @api.model
    def get_rear_wheels_value(self):
        fitment_ids = self.env['fitment.master'].sudo().search([])
        rear_wheels_list = []
        rear_wheels_data = []
        for fitment_id in fitment_ids:
            if fitment_id.rear_wheels_id and fitment_id.rear_wheels_id.id not in rear_wheels_list:
                rear_wheels_data.append((fitment_id.rear_wheels_id.name, fitment_id.rear_wheels_id.name))
                rear_wheels_list.append(fitment_id.rear_wheels_id.id)
        rear_wheels_data.sort()
        return rear_wheels_data

    tag = fields.Char(string="Tag")
    state = fields.Char(string="State")
    mileage = fields.Char(string="Mileage")
    # fitmen_master_id = fields.Many2one('fitment.master', string="Fitment")
    make = fields.Selection(get_make_value, string="Make")
    model = fields.Selection(get_model_value, string="Model")
    year = fields.Selection(get_year_value, string="Year")
    submodel = fields.Selection(get_submodel_value, string="Submodel")
    rear_wheels = fields.Selection(get_rear_wheels_value, string="Wheel Configuration")
    tire_size_front = fields.Char(string="Tire Size (Front)")
    tire_size_rear = fields.Char(string="Tire Size (Rear))")
    engine_type = fields.Char(string="Engine Type")
    vin_number = fields.Char(string="VIN #")
    partner_id = fields.Many2one('res.partner', string="Customer")
    prev_user_vehicle = fields.Float()



class ResPartner(models.Model):
    _inherit = 'res.partner'

    vehicle_info_ids = fields.One2many('vehicle.information', 'partner_id', string="Vehicle Information")
    partner_invoice_history_ids = fields.One2many('res.partner.invoice.history', 'partner_id', string="Partner Invoice History")

    show_vehicle_page = fields.Boolean(
        compute='_compute_show_vehicle_page'
    )

    # Compute the boolean field 'show_vehicle_page' based on a system parameter
    def _compute_show_vehicle_page(self):
        partsync_customer_vehicle = self.env['ir.config_parameter'].sudo().get_param('mmy_config.partsync_customer_vehicle')
        for rec in self:
            rec.show_vehicle_page = partsync_customer_vehicle

class ResPartnerInvoiceHistory(models.Model):
    _name = 'res.partner.invoice.history'

    partner_id = fields.Many2one('res.partner', string="Partner")
    type = fields.Selection([('A/P Invoice', 'A/P Invoice'), ('A/R Invoice', 'A/R Invoice'), ('A/P Credit', 'A/P Credit'),('A/R Credit', 'A/R Credit')], default='A/P Invoice',
                                            string="Type")
    inv_type = fields.Char('Invoice Type')
    date = fields.Date("Date")
    number = fields.Char("Number")
    memo = fields.Char("Memo")
    name = fields.Char("Name")
    item = fields.Char("Item")
    qty = fields.Float("Qty")
    sales_price = fields.Float("Sales Price")
    amount = fields.Float("Amount")
    balance = fields.Float("Balance")



class ProjectProject(models.Model):
    _inherit = 'project.project'

    vehicle_info_id = fields.Many2one('vehicle.information', string="Select Customer Vehicle")

    tag = fields.Char(string="Tag")
    state = fields.Char(string="State")
    mileage = fields.Char(string="Mileage")
    make = fields.Char(string="Make")
    model = fields.Char(string="Model")
    year = fields.Char(string="Year")

    show_vehicle_page = fields.Boolean(
        compute='_compute_show_vehicle_page'
    )

    # Compute the boolean field 'show_vehicle_page' based on a system parameter
    def _compute_show_vehicle_page(self):
        partsync_customer_vehicle = self.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_customer_vehicle')
        for rec in self:
            rec.show_vehicle_page = partsync_customer_vehicle

    @api.model_create_multi
    def create(self, vals_list):
        """
        Create multiple ProjectProject records and auto-fill vehicle fields from vehicle_info_id
        """
        for vals in vals_list:
            if vals.get('vehicle_info_id'):
                vehicle_id = self.env['vehicle.information'].browse(vals['vehicle_info_id'])
                vals.update(dict(
                    tag=vehicle_id.tag,
                    state=vehicle_id.state,
                    make=vehicle_id.make,
                    model=vehicle_id.model,
                    year=vehicle_id.year
                ))
        return super(ProjectProject, self).create(vals_list)

    def write(self, vals):
        """
        Update vehicle fields when vehicle_info_id is changed in write
        """
        if vals.get('vehicle_info_id'):
            vehicle_id = self.env['vehicle.information'].search([('id', '=', vals.get('vehicle_info_id'))])
            if vehicle_id:
                vals.update({
                    'tag': vehicle_id.tag,
                    'state': vehicle_id.state,
                    'make': vehicle_id.make,
                    'model': vehicle_id.model,
                    'year': vehicle_id.year
                })
        # Clear vehicle fields if vehicle_info_id is explicitly removed
        if 'vehicle_info_id' in vals.keys() and not vals.get('vehicle_info_id'):
            vals.update({
                'tag': '',
                'state': '',
                'make': '',
                'model': '',
                'year': ''
            })
        return super(ProjectProject, self).write(vals)

    @api.onchange('vehicle_info_id')
    def change_vehicle_info(self):
        """
        method used for auto-fill vehicle fields when vehicle_info_id is changed in the form
        """
        for rec_id in self:
            if rec_id.vehicle_info_id:
                rec_id.tag = rec_id.vehicle_info_id.tag
                rec_id.state = rec_id.vehicle_info_id.state
                rec_id.make = rec_id.vehicle_info_id.make
                rec_id.model = rec_id.vehicle_info_id.model
                rec_id.year = rec_id.vehicle_info_id.year
                rec_id.mileage = ''

    @api.onchange('partner_id')
    def change_partner_id(self):
        """
        method used for clear vehicle fields when partner_id is changed
        """
        for rec_id in self:
            if rec_id.partner_id:
                rec_id.vehicle_info_id = ''
                rec_id.tag = ''
                rec_id.state = ''
                rec_id.make = ''
                rec_id.model = ''
                rec_id.year = ''
                rec_id.mileage = ''
