# -*- coding: utf-8 -*-

from odoo import models, api, fields


class VehicleInformation(models.Model):
    _inherit = 'vehicle.information'

    active = fields.Boolean(string='Active', default=True)


class Http(models.AbstractModel):
    _inherit = "ir.http"

    @api.model
    def get_frontend_session_info(self):
        """
        Extends the frontend session information by adding vehicle-related data
        (make, year, model, submodel, and rear wheels) for use on the website.
        """
        session_info = super(Http, self).get_frontend_session_info()
        session_info.update({
            'makes': self.env['vehicle.information'].get_make_value(),
            'years': self.env['vehicle.information'].get_year_value(),
            'models': self.env['vehicle.information'].get_model_value(),
            'submodels': self.env['vehicle.information'].get_submodel_value(),
            'rear_wheels': self.env['vehicle.information'].get_rear_wheels_value(),
        })
        return session_info


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _load_menus_blacklist(self):
        """
        Extends the default menu blacklist to hide specific fitment and import menus
        based on configuration parameters related to product filtering and customer import.
        """
        res = super()._load_menus_blacklist()
        partsync_product_filtering = self.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_product_filtering')
        partsync_customer_import = self.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_customer_import')
        if not partsync_product_filtering:
            # res.append(self.env.ref('project_cars_enhancement.mmy_fiftment_management_menu').id)
            res.append(self.env.ref('project_cars_enhancement.menu_customer_product_fitment_mapping_master').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_make').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_model').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_submodel').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_year').id)
            res.append(self.env.ref('project_cars_enhancement.menu_vehicle_patform').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_master').id)
            res.append(self.env.ref('project_cars_enhancement.menu_vehicle_information').id)
        if not partsync_customer_import:
            res.append(self.env.ref('project_cars_enhancement.menu_import_customer_product_master_mmy_app').id)
            res.append(self.env.ref('project_cars_enhancement.menu_import_fitment_master_mmy_app').id)
            res.append(self.env.ref('project_cars_enhancement.menu_import_fitment_data_mmy_app').id)
        return res

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _get_partsync_customer_vehicle(self):
        """
        Retrieves the configuration parameter that determines
        whether the customer vehicle synchronization is enabled.
        """
        return self.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_customer_vehicle')
