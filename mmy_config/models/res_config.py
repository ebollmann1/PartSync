# -*- coding: utf-8 -*-

from odoo import fields,models,api,_

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    partsync_product_filtering = fields.Boolean("PPF", readonly=True, default=False, config_parameter='mmy_config.partsync_product_filtering')
    partsync_eCommerce_filtering = fields.Boolean("PEF", readonly=True, default=False, config_parameter='mmy_config.partsync_eCommerce_filtering')
    partsync_customer_import = fields.Boolean("PCI", readonly=True, default=False, config_parameter='mmy_config.partsync_customer_import')
    partsync_customer_vehicle = fields.Boolean("PCV", readonly=True, default=False, config_parameter='mmy_config.partsync_customer_vehicle')
    show_partsync = fields.Boolean("Show PartSync", default=False, config_parameter='mmy_config.show_partsync')

class IrConfigParameter(models.Model):
    _inherit = 'ir.config_parameter'

    def write(self, vals):
        """
        Override to manage PartSync license validation and feature activation based on encoded config value.
        """
        res = super(IrConfigParameter, self).write(vals)
        for rec in self:
            if rec.key == 'mmy.PartSync_Config':
                enterprise_code = self.env['ir.config_parameter'].sudo().get_param('database.enterprise_code')
                if len(rec.value) > 10:
                    ent_text = ''
                    try:
                        ent_text = bytes.fromhex(rec.value[:-8]).decode('utf-8')
                    except:
                        pass

                    if ent_text == enterprise_code:
                        if rec.value[-8:-6] == '31':
                            self.env['ir.config_parameter'].set_param("mmy_config.partsync_product_filtering", True)
                        else:
                            self.env['ir.config_parameter'].set_param("mmy_config.partsync_product_filtering", False)

                        if rec.value[-6:-4] == '31':
                            self.env['ir.config_parameter'].set_param("mmy_config.partsync_eCommerce_filtering", True)
                        else:
                            self.env['ir.config_parameter'].set_param("mmy_config.partsync_eCommerce_filtering", False)

                        if rec.value[-4:-2] == '31':
                            self.env['ir.config_parameter'].set_param("mmy_config.partsync_customer_import", True)
                        else:
                            self.env['ir.config_parameter'].set_param("mmy_config.partsync_customer_import", False)

                        if rec.value[-2:] == '31':
                            self.env['ir.config_parameter'].set_param("mmy_config.partsync_customer_vehicle", True)
                        else:
                            self.env['ir.config_parameter'].set_param("mmy_config.partsync_customer_vehicle", False)

                        if rec.value[-8:-6] == '31' or rec.value[-6:-4] == '31' or  rec.value[-4:-2] == '31' or rec.value[-2:] == '31':
                            self.env['ir.config_parameter'].set_param("mmy_config.show_partsync", True)
                        else:
                            self.env['ir.config_parameter'].set_param("mmy_config.show_partsync", False)
                    else:
                        self.env['ir.config_parameter'].set_param("mmy_config.partsync_product_filtering", False)
                        self.env['ir.config_parameter'].set_param("mmy_config.partsync_eCommerce_filtering", False)
                        self.env['ir.config_parameter'].set_param("mmy_config.partsync_customer_import", False)
                        self.env['ir.config_parameter'].set_param("mmy_config.partsync_customer_vehicle", False)
                        self.env['ir.config_parameter'].set_param("mmy_config.show_partsync", False)

                else:
                    self.env['ir.config_parameter'].set_param("mmy_config.partsync_product_filtering", False)
                    self.env['ir.config_parameter'].set_param("mmy_config.partsync_eCommerce_filtering", False)
                    self.env['ir.config_parameter'].set_param("mmy_config.partsync_customer_import", False)
                    self.env['ir.config_parameter'].set_param("mmy_config.partsync_customer_vehicle", False)
                    self.env['ir.config_parameter'].set_param("mmy_config.show_partsync", False)
        return res
