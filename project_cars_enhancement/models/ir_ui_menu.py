from odoo import models, api, fields

class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'
    
    def _load_menus_blacklist(self):
        """
        Dynamically hide specific menus based on system parameters.

        - If 'mmy_config.partsync_product_filtering' is not enabled,
            several fitment-related menus are added to the blacklist.
        - If 'mmy_config.partsync_customer_import' is not enabled,
            customer product import menus are added to the blacklist.
        """
        res = super()._load_menus_blacklist()
        partsync_product_filtering = self.env['ir.config_parameter'].sudo().get_param \
            ('mmy_config.partsync_product_filtering')
        partsync_customer_import = self.env['ir.config_parameter'].sudo().get_param \
            ('mmy_config.partsync_customer_import')
        if not partsync_product_filtering:
            # res.append(self.env.ref('project_cars_enhancement.mmy_fiftment_management_menu').id)
            res.append(self.env.ref('project_cars_enhancement.menu_customer_product_fitment_mapping_master').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_make').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_model').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_submodel').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_rear_wheels').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_year').id)
            res.append(self.env.ref('project_cars_enhancement.menu_vehicle_patform').id)
            res.append(self.env.ref('project_cars_enhancement.menu_fitment_master').id)
            res.append(self.env.ref('project_cars_enhancement.menu_vehicle_information').id)
        
        if not partsync_customer_import:
            res.append(self.env.ref('project_cars_enhancement.menu_import_customer_product_master_mmy_app').id)
            res.append(self.env.ref('project_cars_enhancement.menu_import_fitment_master_mmy_app').id)
            res.append(self.env.ref('project_cars_enhancement.menu_import_fitment_data_mmy_app').id)
        return res