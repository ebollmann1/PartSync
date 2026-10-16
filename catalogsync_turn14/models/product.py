from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductProduct(models.Model):
    _inherit = "product.product"

    t14_item_id = fields.Char(string="Turn 14 Item ID", index=True, copy=False)

    @api.constrains("t14_item_id", "company_id")
    def _check_t14_item_identity(self):
        if self.env.context.get('skip_t14_identity_check'):
            return
        # company_id is delegated to product.template, not a SQL column here.
        for product in self.filtered("t14_item_id"):
            if self.with_context(active_test=False).search_count([
                ("t14_item_id", "=", product.t14_item_id),
                ("company_id", "=", product.company_id.id),
                ("id", "!=", product.id),
            ], limit=1):
                raise ValidationError(_("Turn 14 Item ID must be unique per company."))


class ProductTemplate(models.Model):
    _inherit = "product.template"

    t14_item_id = fields.Char(
        string="Turn 14 Item ID", compute="_compute_t14_item_id", readonly=True,store=True
    )

    @api.depends("product_variant_ids.t14_item_id")
    def _compute_t14_item_id(self):
        for template in self:
            imported = template.with_context(active_test=False).product_variant_ids.filtered("t14_item_id")
            template.t14_item_id = imported.t14_item_id if len(imported) == 1 else False
