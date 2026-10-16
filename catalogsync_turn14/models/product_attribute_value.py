from odoo import fields, models


class ProductAttributeValue(models.Model):
    _inherit = "product.attribute.value"

    t14_brand_id = fields.Char(string="Turn 14 Brand ID", index=True, copy=False)

    _t14_brand_uniq = models.Constraint(
        "unique(attribute_id, t14_brand_id)",
        "Turn 14 Brand ID must be unique within its attribute.",
    )
