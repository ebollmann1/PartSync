import base64
import concurrent.futures
import json
import logging
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from odoo import fields, models, _
from odoo.exceptions import UserError
from odoo.tools.sql import escape_psql

_logger = logging.getLogger(__name__)


class Turn14ProductImport(models.AbstractModel):
    _inherit = "turn14.sync"

    def _get_cached_item_flags(self):
        """Pre-fetch or create the 4 static flag attribute values once per batch."""
        flags = {}
        for key, label in (("powersports_indicator", "Powersports"), ("clearance_item", "Clearance")):
            attribute = self.env["product.attribute"].with_context(active_test=False).search([("name", "=ilike", label)], limit=1)
            if not attribute:
                attribute = self.env["product.attribute"].create({"name": label, "create_variant": "no_variant"})
            elif not attribute.active:
                attribute.active = True
            self._upsert_ir_model_data("product.attribute", attribute.id, f"catalogsync_turn14.attribute_{key}")
            for is_true, val_name in ((True, "Yes"), (False, "No")):
                val = self.env["product.attribute.value"].with_context(active_test=False).search([
                    ("attribute_id", "=", attribute.id), ("name", "=ilike", val_name),
                ], limit=1)
                if not val:
                    val = self.env["product.attribute.value"].create({"attribute_id": attribute.id, "name": val_name})
                elif not val.active:
                    val.active = True
                self._upsert_ir_model_data("product.attribute.value", val.id, f"catalogsync_turn14.value_{key}_{val_name.lower()}")
                flags[(key, is_true)] = val
        return flags

    def _import_item(self, company, item, cache=None, image_queue=None):
        """Import a single validated item with fast batch caching; supplier info is deferred."""
        self = self.with_company(company).with_context(
            lang=None,
            tracking_disable=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
            mail_auto_delete=True,
        )
        attrs = item["attributes"]
        products = self.env["product.product"].with_context(
            active_test=False,
            tracking_disable=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
            mail_auto_delete=True,
        )
        item_id = item["id"]

        # If running standalone outside a batch, acquire the transaction lock
        if not cache:
            self._lock_reference(f"products:{company.id}")

        # Instant in-memory product lookup or single database search
        if cache and "existing_products" in cache and item_id in cache["existing_products"]:
            product = cache["existing_products"][item_id]
        else:
            product = products.search([("company_id", "=", company.id), ("t14_item_id", "=", item_id)], limit=1)

        # Brand resolution with batch caching
        brand_name = attrs.get("brand")
        brand_id = attrs.get("brand_id")
        brand_key = (str(brand_name or ""), str(brand_id or ""))
        if cache and "brands" in cache and brand_key in cache["brands"]:
            brand = cache["brands"][brand_key]
        else:
            brand = self._resolve_brand_value(company, brand_name, brand_id)
            if cache and "brands" in cache:
                cache["brands"][brand_key] = brand

        attribute_values = brand | self._item_flag_values(attrs, cache=cache)
        values = {"name": attrs["product_name"], "type": "consu"}
        if company.t14_default_category_id:
            values["categ_id"] = company.t14_default_category_id.id
        routes = self._resolve_item_routes(
            company,
            attrs,
            product.route_ids if product else self.env["stock.route"],
        )
        values["route_ids"] = [fields.Command.set(routes.ids)]
        if "part_description" in attrs:
            values["description_sale"] = attrs["part_description"] or False
        if "active" in attrs:
            values["is_published"] = attrs["active"]
        if "regular_stock" in attrs:
            values["is_storable"] = attrs["regular_stock"]
        if "warehouse_availability" in attrs:
            values["sale_ok"] = any(row["can_place_order"] for row in attrs["warehouse_availability"])
        if "category" in attrs:
            categories = self._resolve_website_categories(attrs.get("category"), attrs.get("subcategory"), cache=cache)
            values["public_categ_ids"] = [fields.Command.set(categories.ids)]

        dimension_vals = {}
        if "dimensions" in attrs and attrs["dimensions"]:
            boxes = attrs["dimensions"]
            total_weight = sum(box.get("weight", 0.0) or 0.0 for box in boxes if isinstance(box, dict))
            if total_weight:
                values["weight"] = total_weight
            first_box = boxes[0] if isinstance(boxes[0], dict) else {}
            length = first_box.get("length")
            width = first_box.get("width")
            height = first_box.get("height")
            if length is not None:
                dimension_vals["product_length"] = str(length)
            if width is not None:
                dimension_vals["product_width"] = str(width)
            if height is not None:
                dimension_vals["product_height"] = str(height)
            if length is not None and width is not None and height is not None:
                values["volume"] = float(length) * float(width) * float(height)
            values.update(dimension_vals)

        barcode = (attrs.get("barcode") or "").strip()
        if barcode:
            if not product or product.barcode != barcode:
                conflict = products.search([
                    ("barcode", "=", barcode), ("company_id", "in", [False, company.id]),
                    ("id", "!=", product.id or 0),
                ], limit=1)
                if conflict:
                    _logger.warning("Turn 14 item %s skipped: barcode belongs to product %s.", item_id, conflict.id)
                    return "skipped"
            values["barcode"] = barcode

        thumbnail_url = attrs.get("thumbnail")
        if thumbnail_url and (not product or not product.image_1920):
            b64_img = self._download_image_b64(thumbnail_url)
            if b64_img:
                values["image_1920"] = b64_img

        created = not product
        if created:
            # Include variant-producing Brand attributes at template creation
            values.update({
                "company_id": company.id,
                "attribute_line_ids": [fields.Command.create({
                    "attribute_id": value.attribute_id.id,
                    "value_ids": [fields.Command.set(value.ids)],
                }) for value in attribute_values],
            })
            template = self.env["product.template"].with_context(
                tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True, mail_notrack=True,
            ).create(values)
            product = template.product_variant_id or template._create_product_variant(
                template._get_first_possible_combination(),
            )
            if not product:
                raise UserError(_("Cannot create a product variant for Turn 14 item %s.", item_id))
            segment = brand.i_r_segment_value.name if brand else False
            reference = (
                f"{attrs['mfr_part_number']}-{segment}"
                if segment and attrs.get("mfr_part_number") else attrs["part_number"]
            )
            product_vals = {
                "default_code": reference,
                "t14_item_id": item_id,
            }
            product_vals.update({
                k: v for k, v in dimension_vals.items()
                if k in product._fields and k != "attribute_line_ids"
            })
            product.with_context(
                skip_default_code=True, tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True, mail_notrack=True,
            ).write(product_vals)
            if cache and "existing_products" in cache:
                cache["existing_products"][item_id] = product
        else:
            template = product.product_tmpl_id
            references = {variant.id: variant.default_code for variant in template.product_variant_ids}
            self._apply_item_attributes(product, attribute_values)
            values["t14_item_id"] = item_id
            if "public_categ_ids" in values and template.public_categ_ids.ids == (categories.ids if "category" in attrs else []):
                values.pop("public_categ_ids", None)
            product.with_context(
                tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True, mail_notrack=True,
            ).write(values)
            template_dim = {k: v for k, v in dimension_vals.items() if k in template._fields}
            if template_dim:
                template.with_context(
                    tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True, mail_notrack=True,
                ).write(template_dim)
            product_dim = {k: v for k, v in dimension_vals.items() if k in product._fields}
            if product_dim:
                template.product_variant_ids.with_context(
                    tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True, mail_notrack=True,
                ).write(product_dim)
            for variant in template.product_variant_ids:
                if variant.id in references and variant.default_code != references[variant.id]:
                    variant.with_context(skip_default_code=True, tracking_disable=True).write({"default_code": references[variant.id]})

        self._bind_source(product, company, "item", item_id)
        self._assign_existing_pricelist(company, product, attrs, cache=cache)
        self._apply_alternative_product(company, template, attrs)
        self._store_item_payload(product, item)

        # Fallback if image was not yet set
        if thumbnail_url and not product.image_1920:
            if image_queue is not None:
                image_queue.append((product.id, thumbnail_url))
            else:
                self._import_item_image(product, thumbnail_url)

        return "created" if created else "updated"

    # ── Batch import (called by job_sync_items_page) ────────────────

    def _import_items_batch(self, company, normalized_items, cache, image_queue):
        """Batch-import normalized items — two-pass strategy for max throughput.

        Pass 1: classify all items, resolve shared data, check barcodes in batch.
        Pass 2: batch-create new templates, per-item-update existing, batch post-process.
        """
        self = self.with_company(company).with_context(
            lang=None,
            tracking_disable=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            mail_notrack=True,
            mail_auto_delete=True,
            skip_default_code=True,
            skip_t14_identity_check=True,
            skip_cpm_update=True,
        )
        Products = self.env["product.product"].with_context(active_test=False)
        counts = {"created": 0, "updated": 0, "skipped": 0}
        all_results = []  # [(product, template, item)] for batch post-processing

        # Deduplicate (keep last occurrence if API returns duplicates)
        seen_ids = {}
        for item in normalized_items:
            seen_ids[item["id"]] = item
        normalized_items = list(seen_ids.values())

        # ── Batch barcode conflict check ───────────────────────────────
        barcode_checks = {}  # barcode -> [(item_id, existing_product_id)]
        seen_barcodes = {}   # barcode -> first item_id (intra-batch dedup)
        for item in normalized_items:
            barcode = (item["attributes"].get("barcode") or "").strip()
            if not barcode:
                continue
            item_id = item["id"]
            if barcode in seen_barcodes:
                continue  # first item wins
            seen_barcodes[barcode] = item_id
            existing = cache["existing_products"].get(item_id)
            if not existing or existing.barcode != barcode:
                barcode_checks.setdefault(barcode, []).append(
                    (item_id, existing.id if existing else 0)
                )

        conflicted = set()
        if barcode_checks:
            conflicts = Products.search([
                ("barcode", "in", list(barcode_checks)),
                ("company_id", "in", [False, company.id]),
            ])
            for prod in conflicts:
                for item_id, existing_id in barcode_checks.get(prod.barcode, []):
                    if prod.id != existing_id:
                        conflicted.add(item_id)
                        _logger.warning(
                            "Turn 14 item %s skipped: barcode belongs to product %s.",
                            item_id, prod.id,
                        )

        # ── Pre-fetch images concurrently so products are created with images ──
        image_tasks = []
        for item in normalized_items:
            item_id = item["id"]
            if item_id in conflicted:
                continue
            url = item["attributes"].get("thumbnail")
            if not url:
                continue
            existing = cache["existing_products"].get(item_id)
            if not existing or not existing.image_1920:
                image_tasks.append((item_id, url))

        downloaded_images = self._batch_download_images(image_tasks) if image_tasks else {}

        # ── Classify and prepare all items ─────────────────────────────
        new_items = []      # [(item, tmpl_vals, attribute_values, brand, dim_vals)]
        update_items = []   # [(item, product, write_vals, attribute_values, dim_vals)]

        for item in normalized_items:
            item_id = item["id"]
            if item_id in conflicted:
                counts["skipped"] += 1
                continue

            attrs = item["attributes"]

            # Brand (cached after first call per unique key)
            brand_key = (str(attrs.get("brand") or ""), str(attrs.get("brand_id") or ""))
            if brand_key in cache["brands"]:
                brand = cache["brands"][brand_key]
            else:
                brand = self._resolve_brand_value(
                    company, attrs.get("brand"), attrs.get("brand_id"),
                )
                cache["brands"][brand_key] = brand

            attribute_values = brand | self._item_flag_values(attrs, cache=cache)

            values = {"name": attrs["product_name"], "type": "consu"}
            if company.t14_default_category_id:
                values["categ_id"] = company.t14_default_category_id.id
            if "part_description" in attrs:
                values["description_sale"] = attrs["part_description"] or False
            if "active" in attrs:
                values["is_published"] = attrs["active"]
            if "regular_stock" in attrs:
                values["is_storable"] = attrs["regular_stock"]
            if "warehouse_availability" in attrs:
                values["sale_ok"] = any(
                    r["can_place_order"] for r in attrs["warehouse_availability"]
                )
            if "category" in attrs:
                categories = self._resolve_website_categories(
                    attrs.get("category"), attrs.get("subcategory"), cache=cache,
                )
                values["public_categ_ids"] = [fields.Command.set(categories.ids)]

            dimension_vals = {}
            if attrs.get("dimensions"):
                boxes = attrs["dimensions"]
                total_weight = sum(
                    box.get("weight", 0.0) or 0.0
                    for box in boxes if isinstance(box, dict)
                )
                if total_weight:
                    values["weight"] = total_weight
                first_box = boxes[0] if isinstance(boxes[0], dict) else {}
                length = first_box.get("length")
                width = first_box.get("width")
                height = first_box.get("height")
                if length is not None:
                    dimension_vals["product_length"] = str(length)
                if width is not None:
                    dimension_vals["product_width"] = str(width)
                if height is not None:
                    dimension_vals["product_height"] = str(height)
                if None not in (length, width, height):
                    values["volume"] = float(length) * float(width) * float(height)
                values.update(dimension_vals)

            barcode = (attrs.get("barcode") or "").strip()
            if barcode:
                values["barcode"] = barcode

            # Attach downloaded image directly so it is saved at creation or write time
            if item_id in downloaded_images:
                values["image_1920"] = downloaded_images[item_id]

            existing_product = cache["existing_products"].get(item_id)
            current_routes = (
                existing_product.route_ids if existing_product
                else self.env["stock.route"]
            )
            routes = self._resolve_item_routes(company, attrs, current_routes)
            values["route_ids"] = [fields.Command.set(routes.ids)]
            if existing_product:
                update_items.append(
                    (item, existing_product, values, attribute_values, dimension_vals)
                )
            else:
                new_items.append(
                    (item, values, attribute_values, brand, dimension_vals)
                )

        # ── Batch-create new product templates ─────────────────────────
        if new_items:
            tmpl_vals_list = []
            for _item, values, attribute_values, _brand, _dim in new_items:
                vals = dict(values)
                vals["company_id"] = company.id
                vals["attribute_line_ids"] = [
                    fields.Command.create({
                        "attribute_id": v.attribute_id.id,
                        "value_ids": [fields.Command.set(v.ids)],
                    })
                    for v in attribute_values
                ]
                tmpl_vals_list.append(vals)

            templates = self.env["product.template"].with_context(
                tracking_disable=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                mail_notrack=True,
                skip_default_code=True,
                skip_t14_identity_check=True,
                skip_cpm_update=True,
            ).create(tmpl_vals_list)

            for idx, (item, _values, _av, brand, dimension_vals) in enumerate(new_items):
                template = templates[idx]
                product = (
                    template.product_variant_id
                    or template.product_variant_ids[:1]
                    or template._create_product_variant(
                        template._get_first_possible_combination(),
                    )
                )
                if not product:
                    raise UserError(_(
                        "Cannot create a product variant for Turn 14 item %s.",
                        item["id"],
                    ))
                attrs = item["attributes"]
                segment = brand.i_r_segment_value.name if brand else False
                reference = (
                    f"{attrs['mfr_part_number']}-{segment}"
                    if segment and attrs.get("mfr_part_number")
                    else attrs["part_number"]
                )
                prod_vals = {"default_code": reference, "t14_item_id": item["id"]}
                prod_vals.update({
                    k: v for k, v in dimension_vals.items()
                    if k in product._fields and k != "attribute_line_ids"
                })
                product.with_context(
                    skip_default_code=True,
                    skip_t14_identity_check=True,
                    tracking_disable=True,
                ).write(prod_vals)
                cache["existing_products"][item["id"]] = product
                all_results.append((product, template, item))
                counts["created"] += 1

        # ── Update existing products ───────────────────────────────────
        for item, product, values, attribute_values, dimension_vals in update_items:
            template = product.product_tmpl_id
            references = {v.id: v.default_code for v in template.product_variant_ids}
            self._apply_item_attributes(product, attribute_values)
            values["t14_item_id"] = item["id"]
            attrs = item["attributes"]
            if "public_categ_ids" in values and "category" in attrs:
                categories = self._resolve_website_categories(
                    attrs.get("category"), attrs.get("subcategory"), cache=cache,
                )
                if template.public_categ_ids.ids == categories.ids:
                    values.pop("public_categ_ids", None)
            product.with_context(
                skip_default_code=True,
                skip_t14_identity_check=True,
                tracking_disable=True,
            ).write(values)
            tmpl_dim = {k: v for k, v in dimension_vals.items() if k in template._fields}
            if tmpl_dim:
                template.write(tmpl_dim)
            prod_dim = {k: v for k, v in dimension_vals.items() if k in product._fields}
            if prod_dim:
                template.product_variant_ids.write(prod_dim)
            for variant in template.product_variant_ids:
                if variant.id in references and variant.default_code != references[variant.id]:
                    variant.with_context(skip_default_code=True).write(
                        {"default_code": references[variant.id]},
                    )
            all_results.append((product, template, item))
            counts["updated"] += 1

        # ── Batch post-processing ──────────────────────────────────────
        if all_results:
            self._batch_bind_sources(
                [(p, item["id"]) for p, _t, item in all_results],
                company, "item",
            )
            for product, _template, item in all_results:
                self._assign_existing_pricelist(
                    company, product, item["attributes"], cache=cache,
                )
            self._batch_alternative_products(company, all_results)
            self._batch_store_payloads(company, all_results)
            if image_queue is not None:
                for product, _template, item in all_results:
                    url = item["attributes"].get("thumbnail")
                    if url and not product.image_1920:
                        image_queue.append((product.id, url))

        return counts

    def _resolve_item_routes(self, company, attrs, current_routes=None):
        """Return item routes while preserving routes not managed by Turn 14 settings."""
        configured_routes = (
            company.t14_dropship_route_id
            | company.t14_air_freight_route_id
            | company.t14_carb_route_id
            | company.t14_ltl_freight_route_id
        )
        routes = (current_routes or self.env["stock.route"]) - configured_routes
        if attrs.get("dropship_controller_id") and company.t14_dropship_route_id:
            routes |= company.t14_dropship_route_id
        if attrs.get("air_freight_prohibited") and company.t14_air_freight_route_id:
            routes |= company.t14_air_freight_route_id
        if attrs.get("not_carb_approved") and company.t14_carb_route_id:
            routes |= company.t14_carb_route_id
        if attrs.get("ltl_freight_required") and company.t14_ltl_freight_route_id:
            routes |= company.t14_ltl_freight_route_id
        return routes

    def _batch_alternative_products(self, company, all_results):
        """Batch-resolve alternative product links (one supplier search)."""
        codes_templates = {}  # code -> [template]
        for _product, template, item in all_results:
            code = (item["attributes"].get("alternate_part_number") or "").strip()
            if code:
                codes_templates.setdefault(code, []).append(template)
        if not codes_templates:
            return
        suppliers = self.env["product.supplierinfo"].search([
            ("company_id", "in", [False, company.id]),
            ("product_code", "in", list(codes_templates)),
            ("product_tmpl_id.company_id", "in", [False, company.id]),
        ])
        by_code = {}
        for sup in suppliers:
            by_code.setdefault(sup.product_code, []).append(sup)
        for code, templates in codes_templates.items():
            for template in templates:
                matching = [
                    s for s in by_code.get(code, [])
                    if s.product_tmpl_id.id != template.id
                ]
                alternatives = self.env["product.template"].browse(
                    list({s.product_tmpl_id.id for s in matching})
                ).filtered("active")
                if len(alternatives) == 1:
                    template.write({
                        "alternative_product_ids": [fields.Command.link(alternatives.id)],
                    })
                elif len(alternatives) > 1:
                    _logger.warning(
                        "Turn 14 alternative code %s matches multiple products;"
                        " link deferred.", code,
                    )

    def _batch_store_payloads(self, company, all_results):
        """Batch store raw JSON payloads (one search + one batch create)."""
        if not (company.t14_store_payload or self.env.context.get("store_item_payload")):
            return
        product_ids = [p.id for p, _t, _i in all_results]
        env_prefix = f"Turn14-{company.t14_environment}-"
        existing = self.env["ir.attachment"].search([
            ("res_model", "=", "product.product"),
            ("res_id", "in", product_ids),
            ("name", "=like", env_prefix + "%"),
        ])
        existing_map = {att.res_id: att for att in existing}
        to_create = []
        for product, _template, item in all_results:
            name = f"{env_prefix}{product.t14_item_id}.json"
            raw = json.dumps(
                item, ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")
            vals = {
                "name": name, "res_model": "product.product", "res_id": product.id,
                "company_id": company.id, "type": "binary",
                "mimetype": "application/json",
                "datas": base64.b64encode(raw), "public": False,
            }
            if product.id in existing_map:
                existing_map[product.id].write(vals)
            else:
                to_create.append(vals)
        if to_create:
            self.env["ir.attachment"].create(to_create)

    def _item_flag_values(self, attrs, cache=None):
        if cache and "item_flags" in cache:
            values = self.env["product.attribute.value"]
            for key in ("powersports_indicator", "clearance_item"):
                if key in attrs:
                    val = cache["item_flags"].get((key, bool(attrs[key])))
                    if val:
                        values |= val
            return values

        self._lock_reference("item_attributes")
        values = self.env["product.attribute.value"]
        for key, label in (("powersports_indicator", "Powersports"), ("clearance_item", "Clearance")):
            if key not in attrs:
                continue
            attribute = self.env["product.attribute"].with_context(active_test=False).search([("name", "=ilike", label)], limit=1)
            if not attribute:
                attribute = self.env["product.attribute"].create({"name": label, "create_variant": "no_variant"})
            elif not attribute.active:
                attribute.active = True
            self._upsert_ir_model_data("product.attribute", attribute.id, f"catalogsync_turn14.attribute_{key}")
            name = "Yes" if attrs[key] else "No"
            value = values.with_context(active_test=False).search([
                ("attribute_id", "=", attribute.id), ("name", "=ilike", name),
            ], limit=1)
            if not value:
                value = values.create({"attribute_id": attribute.id, "name": name})
            elif not value.active:
                value.active = True
            values |= value
            self._upsert_ir_model_data("product.attribute.value", value.id, f"catalogsync_turn14.value_{key}_{name.lower()}")
        return values

    def _apply_item_attributes(self, product, values):
        template = product.product_tmpl_id
        for value in values:
            line = template.attribute_line_ids.filtered(lambda row: row.attribute_id == value.attribute_id)
            if value.attribute_id.create_variant != "no_variant":
                assigned = product.product_template_attribute_value_ids.product_attribute_value_id
                if value not in assigned:
                    raise UserError(_(
                        "Product %(product)s uses variant-producing attribute %(attribute)s. "
                        "Assign its existing variant before importing a different value.",
                        product=product.display_name, attribute=value.attribute_id.name,
                    ))
                continue
            if line:
                if line.value_ids != value:
                    line.write({"value_ids": [fields.Command.set(value.ids)]})
            else:
                self.env["product.template.attribute.line"].create({
                    "product_tmpl_id": template.id, "attribute_id": value.attribute_id.id,
                    "value_ids": [fields.Command.set(value.ids)],
                })

    def _resolve_website_categories(self, category_name, subcategory_name, cache=None):
        cache_key = (str(category_name or ""), str(subcategory_name or ""))
        if cache and "categories" in cache and cache_key in cache["categories"]:
            return cache["categories"][cache_key]

        self._lock_reference("categories")
        categories = self.env["product.public.category"]
        parent = categories
        for name in (category_name, subcategory_name):
            if not name or not name.strip():
                continue
            category = categories.search([
                ("name", "=ilike", escape_psql(name.strip())), ("parent_id", "=", parent.id or False),
            ], limit=1)
            if not category:
                category = categories.create({"name": name.strip(), "parent_id": parent.id or False})
            categories |= category
            parent = category

        if cache and "categories" in cache:
            cache["categories"][cache_key] = categories
        return categories

    def _assign_existing_pricelist(self, company, product, attrs, cache=None):
        """Resolve the existing price group; keep its applicable pricing rules."""
        name = (attrs.get("price_group") or "").strip()
        if not name:
            return self.env["product.pricelist"]
        if cache and "pricelists" in cache and name in cache["pricelists"]:
            return cache["pricelists"][name]

        pricelist = self.env["product.pricelist"].search([
            ("company_id", "in", [False, company.id]), ("name", "=ilike", escape_psql(name)),
        ], order="company_id, id", limit=1)
        if pricelist:
            _logger.info(
                "Turn 14 item %s matched pricelist %s; existing pricing rules are preserved.",
                product.t14_item_id or product.id, pricelist.id,
            )
        if cache and "pricelists" in cache:
            cache["pricelists"][name] = pricelist
        return pricelist

    def _apply_alternative_product(self, company, template, attrs):
        code = (attrs.get("alternate_part_number") or "").strip()
        if not code:
            return
        suppliers = self.env["product.supplierinfo"].search([
            ("company_id", "in", [False, company.id]),
            ("product_code", "=", code),
            ("product_tmpl_id.company_id", "in", [False, company.id]),
            ("product_tmpl_id", "!=", template.id),
        ])
        alternatives = suppliers.product_tmpl_id.filtered("active")
        if len(alternatives) == 1:
            template.write({"alternative_product_ids": [fields.Command.link(alternatives.id)]})
        elif len(alternatives) > 1:
            _logger.warning("Turn 14 alternative code %s matches multiple products; link deferred.", code)

    def _store_item_payload(self, product, item):
        """Keep source-only metadata as an attachment when explicitly enabled."""
        if not (product.company_id.t14_store_payload or self.env.context.get("store_item_payload")):
            return
        name = f"Turn14-{product.company_id.t14_environment}-{product.t14_item_id}.json"
        attachments = self.env["ir.attachment"]
        attachment = attachments.search([
            ("res_model", "=", "product.product"), ("res_id", "=", product.id), ("name", "=", name),
        ], limit=1)
        raw = json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        values = {
            "name": name, "res_model": "product.product", "res_id": product.id,
            "company_id": product.company_id.id, "type": "binary", "mimetype": "application/json",
            "datas": base64.b64encode(raw),
            "public": False,
        }
        if attachment:
            attachment.write(values)
        else:
            attachments.create(values)

    @classmethod
    def _download_image_b64(cls, url, session=None):
        """Download a single Turn 14 thumbnail and return base64 string or None."""
        if not url:
            return None
        parsed = urlsplit(url)
        # Only fetch Turn 14's documented asset hosts; API data must not permit local requests.
        if parsed.scheme != "https" or parsed.hostname != "d32vzsop7y1h3k.cloudfront.net" or parsed.port not in (None, 443):
            return None
        req_client = session or requests
        try:
            with req_client.get(url, timeout=(5, 15), stream=True, allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("image/"):
                    return None
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 8 * 1024 * 1024:
                        return None
                return base64.b64encode(content).decode("ascii")
        except (requests.RequestException, ValueError, Exception) as error:
            _logger.debug("Turn 14 thumbnail download failed for %s: %s", url, error)
            return None

    def _batch_download_images(self, items_with_urls):
        """Download multiple images concurrently using ThreadPoolExecutor.

        :param items_with_urls: list of (item_id, url)
        :return: dict of {item_id: base64_image_str}
        """
        if not items_with_urls:
            return {}

        results = {}
        max_workers = min(15, len(items_with_urls))

        def _worker(item_id, url, session):
            return item_id, self._download_image_b64(url, session=session)

        with requests.Session() as session:
            adapter = HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers)
            session.mount("https://", adapter)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(_worker, item_id, url, session)
                    for item_id, url in items_with_urls
                ]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        item_id, b64_img = future.result()
                        if b64_img:
                            results[item_id] = b64_img
                    except Exception as exc:
                        _logger.debug("Image worker exception: %s", exc)

        return results

    def _import_item_image(self, product, url, session=None):
        if not url or product.image_1920:
            return False
        b64 = self._download_image_b64(url, session=session)
        if b64:
            with self.env.cr.savepoint():
                product.image_1920 = b64
            return True
        return False
