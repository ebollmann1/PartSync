from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    t14_environment = fields.Selection(related="company_id.t14_environment", readonly=False)
    t14_client_id = fields.Char(related="company_id.t14_client_id", readonly=False)
    t14_client_secret = fields.Char(related="company_id.t14_client_secret", readonly=False)
    t14_product_batch_size = fields.Integer(related="company_id.t14_product_batch_size", readonly=False)
    t14_test_import = fields.Boolean(related="company_id.t14_test_import", readonly=False)
    t14_brand_ids = fields.Char(related="company_id.t14_brand_ids", readonly=False)
    t14_store_payload = fields.Boolean(related="company_id.t14_store_payload", readonly=False)
    t14_default_category_id = fields.Many2one(related="company_id.t14_default_category_id", readonly=False)
    t14_dropship_route_id = fields.Many2one(related="company_id.t14_dropship_route_id", readonly=False)
    t14_air_freight_route_id = fields.Many2one(related="company_id.t14_air_freight_route_id", readonly=False)
    t14_carb_route_id = fields.Many2one(related="company_id.t14_carb_route_id", readonly=False)
    t14_ltl_freight_route_id = fields.Many2one(related="company_id.t14_ltl_freight_route_id", readonly=False)

    def action_t14_test_connection(self):
        """Test the API credentials saved on the selected company."""
        self.ensure_one()
        return self.company_id.action_t14_test_connection()

    def action_t14_import_brands(self):
        """Queue only the configured brands for the selected company."""
        self.ensure_one()
        return self.company_id.action_t14_import_brands()

    def action_t14_import_locations(self):
        """Queue a location import for the selected company."""
        self.ensure_one()
        return self.company_id.action_t14_import_locations()

    def action_t14_sync_catalog(self):
        """Queue product imports restricted to the configured brand IDs."""
        self.ensure_one()
        return self.company_id.action_t14_import_products()

    def action_t14_sync_reference_data(self):
        """Compatibility for older saved actions."""
        self.ensure_one()
        self.company_id.action_t14_import_brands()
        return self.company_id.action_t14_import_locations()
