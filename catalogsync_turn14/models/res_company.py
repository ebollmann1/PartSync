# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from ..services.client import Turn14Client, Turn14Error


class ResCompany(models.Model):
    _inherit = "res.company"

    t14_environment = fields.Selection(
        [
            ("testing", "Testing (apitest.turn14.com)"),
            ("production", "Production (api.turn14.com)"),
        ],
        string="Turn 14 Environment",
        default="testing",
        required=True,
    )
    t14_client_id = fields.Char(
        string="Client ID",
        copy=False,
        groups="base.group_system",
    )
    t14_client_secret = fields.Char(
        string="Client Secret",
        copy=False,
        groups="base.group_system",
    )
    t14_product_batch_size = fields.Integer(
        string="Products Per Job",
        default=100,
        help="Maximum products processed by each queue job.",
    )
    t14_test_import = fields.Boolean(
        string="Test Import",
        help="Import only one product batch per configured brand without queuing the remaining products.",
    )
    t14_brand_ids = fields.Char(
        string="Brand IDs",
        help="Comma-separated Turn 14 brand IDs. Product imports are limited to these brands.",
    )
    t14_store_payload = fields.Boolean(
        string="Store Raw JSON Payload",
        default=False,
        help="Store raw Turn 14 JSON payloads as attachments on products. Keep disabled for high-speed imports.",
    )
    t14_default_category_id = fields.Many2one(
        "product.category",
        string="Default Product Category",
        help="Internal category assigned to products imported from Turn 14.",
    )
    t14_dropship_route_id = fields.Many2one(
        "stock.route",
        string="Dropship Route",
        help="Applied when dropship_controller_id is present in the item data.",
    )
    t14_air_freight_route_id = fields.Many2one(
        "stock.route",
        string="Air Freight Prohibited Route",
        help="Applied when air_freight_prohibited is true.",
    )
    t14_carb_route_id = fields.Many2one(
        "stock.route",
        string="Not CARB Approved Route",
        help="Applied when not_carb_approved is true.",
    )
    t14_ltl_freight_route_id = fields.Many2one(
        "stock.route",
        string="LTL Freight Route",
        help="Applied when ltl_freight_required is true.",
    )

    def _get_t14_client(self):
        """Return an API client configured for this company's environment."""
        self.ensure_one()
        return Turn14Client(
            environment=self.t14_environment,
            client_id=self.t14_client_id,
            client_secret=self.t14_client_secret,
        )

    def _t14_notification(self, message, title=None):
        """Build a standard non-sticky Turn 14 success notification."""
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": title or _("Turn 14"), "message": message,
                       "type": "success", "sticky": False},
        }

    def action_t14_test_connection(self):
        """Verify that the selected company's Turn 14 credentials are valid."""
        self.ensure_one()
        _sync, company = self.env["turn14.sync"]._company_scope(self.id)
        try:
            with company._get_t14_client() as client:
                client.test_connection()
        except Turn14Error as exc:
            raise UserError(str(exc)) from exc
        return {
            "effect": {
                "type": "rainbow_man",
                "message": _("Connection successful!"),
                "fadeout": "slow",
            },
        }

    def _action_t14_import(self, resource):
        """Validate import prerequisites and enqueue the requested resource."""
        self.ensure_one()
        sync, company = self.env["turn14.sync"]._company_scope(self.id)
        # Validate credentials before creating a job, without calling the API.
        with company._get_t14_client() as client:
            if not client.client_id or not client.client_secret:
                raise UserError(_("Enter the client ID and secret for the selected environment first."))
        if resource in {"brands", "items"}:
            brand_ids = company._get_t14_brand_ids()
            for brand_id in brand_ids:
                sync._enqueue(
                    "brand" if resource == "brands" else resource,
                    company,
                    brand_id=brand_id,
                )
        else:
            sync._enqueue(resource, company)
        return self._t14_notification(_(\
            "%(resource)s import queued for %(company)s. You can follow its progress in Queue Jobs.",
            resource=resource.capitalize(),
            company=company.name,
        ))

    def action_t14_import_brands(self):
        """Queue imports for only the configured Turn 14 brands."""
        return self._action_t14_import("brands")

    def action_t14_import_locations(self):
        """Queue the distribution-location import."""
        return self._action_t14_import("locations")

    def action_t14_import_products(self):
        """Queue brand-scoped product imports for all configured brand IDs."""
        return self._action_t14_import("items")

    def _cron_t14_import(self, resource):
        """Queue an enabled scheduled resource import for accessible companies."""
        for company in self.search([("id", "in", self.env.user.company_ids.ids)]):
            with company._get_t14_client() as client:
                if client.client_id and client.client_secret:
                    if resource == "items":
                        for brand_id in company._get_t14_brand_ids():
                            self.env["turn14.sync"]._enqueue(resource, company, brand_id=brand_id)
                    else:
                        self.env["turn14.sync"]._enqueue(resource, company)

    def _get_t14_brand_ids(self):
        """Parse, validate, and deduplicate the configured comma-separated brand IDs."""
        self.ensure_one()
        raw_ids = [value.strip() for value in (self.t14_brand_ids or "").split(",")]
        brand_ids = []
        for brand_id in raw_ids:
            if not brand_id:
                continue
            if not brand_id.isdigit():
                raise UserError(_("Brand IDs must contain only numbers separated by commas."))
            if brand_id not in brand_ids:
                brand_ids.append(brand_id)
        if not brand_ids:
            raise UserError(_("Configure at least one Turn 14 Brand ID before importing products."))
        return brand_ids

    @api.constrains("t14_brand_ids")
    def _check_t14_brand_ids(self):
        """Reject malformed brand lists when company settings are saved."""
        for company in self.filtered("t14_brand_ids"):
            try:
                company._get_t14_brand_ids()
            except UserError as exc:
                raise ValidationError(str(exc)) from exc
