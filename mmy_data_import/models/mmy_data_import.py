import io
import base64
from openpyxl import load_workbook
from odoo.exceptions import ValidationError
from odoo import models, fields, api


class MMYDataImport(models.Model):
    _name = "mmy.data.import"
    _description = "MMY Data Import"
    _rec_name = "file_name"

    file = fields.Binary(string="Excel File", required=True)
    file_name = fields.Char()

    model_id = fields.Many2one(
        "ir.model",
        string="Target Model",
    )

    line_ids = fields.One2many(
        "mmy.data.import.line",
        "import_id",
        string="Column Mapping",
        copy=True,
    )
    batch_row_size = fields.Integer(string="Batch Row", default=100)
    update_existing_if_any = fields.Boolean(
        string="Update Existing Records", default=False
    )
    compare_existing_field_id = fields.Many2one(
        "ir.model.fields",
        string="Compare Existing Field",
        domain="[('model_id', '=', model_id)]",
    )
    compare_existing_field_ttype = fields.Selection(
        string="Compare Existing Field Type", related="compare_existing_field_id.ttype"
    )
    compare_related_model = fields.Char(
        string="Related Model",
        compute="_compute_related_model",
        store=True,
        help="In case compare fiels is One2many, many2many or many2one, specify the related model here.",
    )

    compare_related_field_id = fields.Many2one(
        "ir.model.fields",
        string="Related Model Field",
        domain="[('model', '=', compare_related_model)]",
    )

    @api.depends("compare_existing_field_id")
    def _compute_related_model(self):
        for rec in self:
            if (
                rec.compare_existing_field_id
                and rec.compare_existing_field_id.ttype
                in ("one2many", "many2many", "many2one")
            ):
                rec.compare_related_model = rec.compare_existing_field_id.relation
            else:
                rec.compare_related_model = False

    @api.onchange("update_existing_if_any")
    def _onchange_update_existing(self):
        for rec in self:
            if not rec.update_existing_if_any:
                rec.compare_existing_field_id = False
                rec.compare_related_field_id = False

    def action_load_excel(self):
        self.ensure_one()

        file_data = base64.b64decode(self.file)
        try:
            wb = load_workbook(filename=io.BytesIO(file_data), read_only=True)
        except Exception as e:
            raise ValidationError(
                f"Unable to read the Excel file. Please ensure it's a valid Excel file (.xlsx, .xls, or .ods). Error: {str(e)}"
            )
        ws = wb.active

        headers = []
        for cell in next(ws.iter_rows(min_row=1, max_row=1)):
            headers.append(cell.value)

        self.line_ids.unlink()

        for col in headers:
            self.line_ids.create(
                {
                    "import_id": self.id,
                    "excel_header": col,
                }
            )

    @api.constrains("file", "file_name")
    def _check_excel_file(self):
        for rec in self:
            if rec.file and rec.file_name:
                if not rec.file_name.lower().endswith((".xlsx", ".xls", ".ods")):
                    raise ValidationError("Only Excel files (.xls, .xlsx) are allowed.")

    def action_queue_import(self):
        self.ensure_one()

        if not self.line_ids:
            raise ValidationError(
                "Please load the Excel file and map the columns before importing."
            )

        if not self.model_id:
            raise ValidationError("Please select a target model.")

        file_data = base64.b64decode(self.file)
        try:
            wb = load_workbook(filename=io.BytesIO(file_data), read_only=True)
        except Exception as e:
            raise ValidationError(
                f"Unable to read the Excel file. Please ensure it's a valid Excel file (.xlsx, .xls, or .ods). Error: {str(e)}"
            )
        ws = wb.active

        headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        # Filter out empty rows
        rows = [
            row
            for row in rows
            if any(cell is not None and str(cell).strip() for cell in row)
        ]
        batch_size = self.batch_row_size or 100
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            self.with_delay().import_data_batch(batch, headers)

    def import_data_batch(self, batch, headers):
        header_map = {
            line.excel_header: line.model_field_id.name
            for line in self.line_ids
            if line.model_field_id and line.include_column
        }

        target_model = self.env[self.model_id.model]
        records_to_create = []

        update_mode = self.update_existing_if_any and self.compare_existing_field_id

        # Build key map: which fields are used as unique keys for each one2many
        # e.g., 'seller_ids': ['partner_id', 'product_code']
        o2m_unique_keys = {}
        for line in self.line_ids:
            if (
                line.model_field_id
                and line.model_field_id.ttype == "one2many"
                and line.related_field_id
                and line.include_column
            ):
                o2m_field = line.model_field_id.name
                key_field = line.related_field_id.name
                o2m_unique_keys.setdefault(o2m_field, set()).add(key_field)

        if update_mode:
            # Find compare header
            compare_field_name = self.compare_existing_field_id.name
            compare_related_field_name = (
                self.compare_related_field_id.name
                if self.compare_related_field_id
                else None
            )
            compare_excel_header = next(
                (
                    l.excel_header
                    for l in self.line_ids
                    if (
                        (
                            compare_related_field_name
                            and l.related_field_id.name == compare_related_field_name
                        )
                        or (
                            not compare_related_field_name
                            and l.model_field_id.name == compare_field_name
                        )
                    )
                ),
                None,
            )
            if not compare_excel_header:
                raise ValidationError("Compare field not mapped.")

            for row in batch:
                record_data = {}
                one2many_merged = {}  # {field_name: merged_values_dict}
                compare_value = None

                # Collect all field values
                for idx, cell_value in enumerate(row):
                    cell_value = cell_value.strip() if isinstance(cell_value, str) else cell_value
                    header = headers[idx]
                    if header == compare_excel_header:
                        compare_value = cell_value

                    if header in header_map:
                        field_name = header_map[header]
                        value = self._get_field_value(field_name, cell_value, header)

                        if (
                            isinstance(value, list)
                            and value
                            and value[0][0] == 0
                            and value[0][1] == 0
                            and isinstance(value[0][2], dict)
                        ):
                            # One2many contribution
                            if field_name not in one2many_merged:
                                one2many_merged[field_name] = {}
                            one2many_merged[field_name].update(value[0][2])
                        else:
                            record_data[field_name] = value

                if compare_value is None:
                    # No way to match → create new
                    final_vals = self._prepare_o2m_commands(
                        record_data, one2many_merged, o2m_unique_keys, None
                    )
                    records_to_create.append(final_vals)
                    continue

                # Resolve compare value (many2one etc.)
                search_val = compare_value
                if self.compare_existing_field_id.ttype in (
                    "many2one",
                    "one2many",
                    "many2many",
                ):
                    if (
                        not self.compare_related_model
                        or not self.compare_related_field_id
                    ):
                        raise ValidationError(
                            "Related model/field required for compare field."
                        )
                    rel_rec = self.env[self.compare_related_model].search(
                        [(self.compare_related_field_id.name, "=", compare_value)],
                        limit=1,
                    )
                    if not rel_rec:
                        final_vals = self._prepare_o2m_commands(
                            record_data, one2many_merged, o2m_unique_keys, None
                        )
                        records_to_create.append(final_vals)
                        continue
                    search_val = rel_rec.id

                # Find existing main record
                existing = target_model.search(
                    [(compare_field_name, "=", search_val)], limit=1
                )
                final_vals = self._prepare_o2m_commands(
                    record_data, one2many_merged, o2m_unique_keys, existing
                )

                if existing:
                    existing.write(final_vals)
                else:
                    try:
                        records_to_create.append(final_vals)
                    except Exception as e:
                        raise ValidationError(
                            f"Error preparing record for creation: {str(e)}"
                        )

        else:
            # Pure create mode
            for row in batch:
                record_data = {}
                one2many_merged = {}
                for idx, cell_value in enumerate(row):
                    cell_value = cell_value.strip() if isinstance(cell_value, str) else cell_value
                    header = headers[idx]
                    if header not in header_map:
                        continue
                    field_name = header_map[header]
                    value = self._get_field_value(field_name, cell_value, header)
                    if (
                        isinstance(value, list)
                        and value
                        and value[0][0] == 0
                        and value[0][1] == 0
                    ):
                        one2many_merged.setdefault(field_name, {}).update(value[0][2])
                    else:
                        record_data[field_name] = value
                final_vals = self._prepare_o2m_commands(
                    record_data, one2many_merged, o2m_unique_keys, None
                )
                records_to_create.append(final_vals)

        if records_to_create:
            try:
                target_model.create(records_to_create)
            except Exception as e:
                raise ValidationError(f"Error creating records: {str(e)}")

    def _get_field_value(self, field_name, cell_value, excel_header):
        field = self.env["ir.model.fields"].search(
            [("model", "=", self.model_id.model), ("name", "=", field_name)], limit=1
        )
        if not field or field.ttype not in ("many2one", "many2many", "one2many"):
            return cell_value

        line = self.line_ids.filtered(
            lambda l: l.excel_header == excel_header and l.include_column
        )
        if not (line or line.search_and_select or line.related_field_id):
            return cell_value

        related_model = self.env[line.related_model]
        related_field = line.related_field_id.name
        if field.ttype == "many2one":
            search_field = (
                line.search_and_select.name if line.search_and_select else related_field
            )
            # Case-insensitive search using ilike
            related_record = related_model.search(
                [(search_field, "=", cell_value)], limit=1
            )
            if related_record:
                return related_record.id
            else:
                if line.search_and_select:
                    if related_field:
                        new_rec = related_model.create(
                            {related_field: cell_value}
                        )  # Todo
                        return new_rec.id
                    else:
                        return False
                else:
                    # Only create if no search_and_select (old behavior)
                    new_rec = related_model.create({related_field: cell_value})
                    return new_rec.id
        elif field.ttype == "boolean":
            return bool(cell_value)
        elif field.ttype == "one2many":
            if cell_value:
                rel_field = self.env["ir.model.fields"].search(
                    [("model", "=", line.related_model), ("name", "=", related_field)],
                    limit=1,
                )
                if rel_field and rel_field.ttype == "many2one":
                    rel_rel_model = self.env[rel_field.relation]
                    if line.search_and_select:
                        rel_rel_record = rel_rel_model.search(
                            [(line.search_and_select.name, "=", cell_value)], limit=1
                        )
                    else:
                        rel_rel_record = rel_rel_model.search(
                            [("name", "=", cell_value)], limit=1
                        )
                    if rel_rel_record:
                        value = rel_rel_record.id
                    else:
                        value = rel_rel_model.create({"name": cell_value}).id
                    return [(0, 0, {related_field: value})]
                else:
                    return [(0, 0, {related_field: cell_value})]
            else:
                return None

    def _prepare_o2m_commands(
        self, record_data, one2many_merged, o2m_unique_keys, existing_record
    ):
        """Generate correct (0,0,{}) or (1,id,{}) commands with reliable matching"""
        vals = record_data.copy()

        for o2m_field, values_dict in one2many_merged.items():
            if not values_dict:
                continue

            unique_keys = o2m_unique_keys.get(o2m_field, set())
            if not unique_keys:
                vals[o2m_field] = [(0, 0, values_dict)]
                continue

            if not existing_record:
                vals[o2m_field] = [(0, 0, values_dict)]
                continue

            # Find matching line using safe comparison
            matching_line = None
            o2m_lines = existing_record[o2m_field]

            for line in o2m_lines:
                match = True
                for key_field in unique_keys:
                    if key_field not in values_dict:
                        continue  # skip if not provided in import

                    import_val = values_dict[key_field]
                    line_val = line[key_field]

                    # Special handling for many2one fields (common in supplierinfo: partner_id)
                    field_info = line._fields[key_field]
                    if field_info.type == "many2one":
                        # line_val is record or False, import_val is usually int or False
                        line_id = line_val.id if line_val else False
                        import_id = import_val if isinstance(import_val, int) else False
                        if line_id != import_id:
                            match = False
                            break
                    elif field_info.type in ("char", "text"):
                        # Normalize strings: strip and handle None/False
                        line_str = (line_val or "").strip() if line_val else ""
                        import_str = (str(import_val or "")).strip()
                        if line_str != import_str:
                            match = False
                            break
                    else:
                        # Direct comparison for int, float, boolean, etc.
                        if line_val != import_val:
                            match = False
                            break

                if match:
                    matching_line = line
                    break

            if matching_line:
                # UPDATE existing line
                vals[o2m_field] = [(1, matching_line.id, values_dict)]
            else:
                # CREATE new line
                vals[o2m_field] = [(0, 0, values_dict)]

        return vals
