from odoo import models, fields, api


class MMYDataImportLine(models.Model):
    _name = "mmy.data.import.line"
    _description = "MMY Data Import Line"

    import_id = fields.Many2one("mmy.data.import", ondelete="cascade")

    excel_header = fields.Char(string="Excel Header")

    model_field_id = fields.Many2one(
        "ir.model.fields",
        string="Model Field",
        domain="[('model_id', '=', parent.model_id)]",
    )

    related_model = fields.Char(
        string="Related Model", compute="_compute_related_model", store=True
    )

    related_field_id = fields.Many2one(
        "ir.model.fields",
        string="Related Model Field",
        domain="[('model', '=', related_model)]",
    )
    related_model_m2o = fields.Char(
        string="Related Model for M2O",
        compute="_compute_related_model_m2o",
    )
    search_and_select = fields.Many2one(
        "ir.model.fields",
        string="Select record by Field",
        domain="['|',('model', '=', related_model), ('model', '=', related_model_m2o)]",
    )
    include_column = fields.Boolean(string="Include Column", default=True)

    @api.depends("model_field_id")
    def _compute_related_model(self):
        for rec in self:
            if rec.model_field_id and rec.model_field_id.ttype in (
                "one2many",
                "many2many",
                "many2one",
            ):
                rec.related_model = rec.model_field_id.relation
            else:
                rec.related_model = False

    @api.depends("related_field_id")
    def _compute_related_model_m2o(self):
        for rec in self:
            if rec.related_field_id and rec.related_field_id.ttype == "many2one":
                rec.related_model_m2o = rec.related_field_id.relation
            else:
                rec.related_model_m2o = False
