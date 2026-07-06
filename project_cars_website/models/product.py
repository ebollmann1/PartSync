# -*- coding: utf-8 -*-

from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'


    def _get_combination_info(self, combination=False, product_id=False, add_qty=1.0, uom_id=False, only_template=False):
        """Override for website, where we want to:
            - take the website pricelist if no pricelist is set
            - apply the b2b/b2c setting to the result
        This will work when adding website_id to the context, which is done
        automatically when called from routes with website=True.
        """
        self.ensure_one()

        website = self.env['website'].get_current_website().with_context(self.env.context)
        res = super(ProductTemplate, self)._get_combination_info(
            combination=combination, product_id=product_id, add_qty=add_qty,
            uom_id=uom_id, only_template=only_template)

        url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        res.update({'url': url})
        if website:
            combination = combination or self.env['product.template.attribute.value']

            if not product_id and not combination and not only_template:
                combination = self._get_first_possible_combination()

            if only_template:
                product = self.env['product.product']
            elif product_id:
                product = self.env['product.product'].browse(product_id)
                if (combination - product.product_template_attribute_value_ids):
                    # If the combination is not fully represented in the given product
                    #   make sure to fetch the right product for the given combination
                    product = self._get_variant_for_combination(combination)
            else:
                product = self._get_variant_for_combination(combination)

            res.update({
                'default_code': product.default_code and product.default_code or '',
                'fitment_data': []
            })
            mrp_bom_id = self.env['mrp.bom'].search([('product_id', '=', product.id), ('type', '=', 'phantom')])
            mrp_data = []
            mrp_data_count, final_total = 0, 0
            for bom_line_id in mrp_bom_id.bom_line_ids:
                mrp_data_count += 1
                final_total += round(bom_line_id.product_qty * bom_line_id.sudo().product_id.list_price, 2)
                mrp_data.append({
                    'component': bom_line_id.product_id.name,
                    'quantity': bom_line_id.product_qty,
                    'unit': bom_line_id.product_uom_id.name,
                    'list_price': round(bom_line_id.product_id.list_price, 2),
                    'total': round(bom_line_id.product_qty * bom_line_id.product_id.list_price, 2),
                })
            price = res.get('price')
            res.update(dict(
                mrp_bom=mrp_bom_id and mrp_bom_id or False,
                mrp_data=mrp_data,
                mrp_data_count=mrp_data_count,
                final_total=round(final_total, 2),
                save_price='Save: ' + str(round(price - final_total, 2))))

            if product:
                res.update({'product_package_info': dict(
                    product_height=product.product_height,
                    product_width=product.product_width,
                    product_length=product.product_length,
                    weight=product.weight,
                    weight_uom_name=product.sudo().weight_uom_name,
                    volume=product.volume,
                    volume_uom_name=product.sudo().volume_uom_name,
                )})

                cus_pro_ids = product.customer_product_master_ids
                fit_ids = []
                for cus_pro_id in cus_pro_ids:
                    fit_ids += cus_pro_id.fitment_ids.ids
                fitment_ids = self.env['fitment.master'].browse(fit_ids).sorted(lambda l: (l.year_id, l.make_id, l.model_id, l.submodel_id, l.rear_wheels_id))
                fitment_data = []
                fitment_data_count = len(fitment_ids)
                for fitment_id in fitment_ids:
                    fitment_data.append(dict(
                        year=fitment_id.year_id.name,
                        make=fitment_id.make_id.name,
                        model=fitment_id.model_id.name,
                        submodel=fitment_id.submodel_id.name,
                        rear_wheels=fitment_id.rear_wheels_id.name,
                        vehicle_platform=fitment_id.vehicle_platform_id.name,
                    ))
                res.update({'fitment_data': fitment_data, 'fitment_data_count': fitment_data_count})
        return res

class ProductAttribute(models.Model):
    _inherit = 'product.attribute'

    show_all_attribute_values = fields.Boolean('Show All Attribute Values', copy=False)

    show_all_attribute = fields.Boolean(
        compute='_compute_show_all_attribute'
    )

    def _compute_show_all_attribute(self):
        partsync_eCommerce_filtering = self.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_eCommerce_filtering')
        for rec in self:
            rec.show_all_attribute = partsync_eCommerce_filtering

class Productproduct(models.Model):
    _inherit = "product.product"

    def product_merge_product(self):
        # Wilwood_MWD_OEM_Price_List_January_2026 import 140.1 - file script
        # main_dict = {'140-9192': {'main_product': 68810, 'child_product': [68810, 68811, 68812, 68813]}}
        main_dict = {}
        for product in self:
            split_default_code = product.default_code.split('-')
            if len(split_default_code) == 2:
                if product.default_code not in main_dict:
                    main_dict[product.default_code] = {'main_product': product.id, 'child_product': [product.id]}
            elif len(split_default_code) > 2:
                default_code = split_default_code[0] +'-'+ split_default_code[1]
                if default_code in main_dict:
                    main_dict[default_code]['child_product'] += [product.id]
                else:
                    main_dict[default_code] = {'main_product': product.id, 'child_product': [product.id]}

        for default_code in main_dict:
            print("\n ++++++++++ main_dict ++++++", main_dict[default_code])
            main_product = self.env['product.product'].browse(main_dict[default_code].get('main_product'))
            child_product = self.env['product.product'].browse(main_dict[default_code].get('child_product'))
            print("\n +++++++ main_product +++++++", main_product)
            print("\n +++++++ child_product +++++++", child_product)
            attributes_dict = {}
            default_code_dict = {}
            for child_product_id in child_product:
                for attribute_line_id in child_product_id.attribute_line_ids:
                    if attribute_line_id.attribute_id.id in attributes_dict:
                        attributes_dict[attribute_line_id.attribute_id.id] += attribute_line_id.value_ids.ids
                    else:
                        attributes_dict[attribute_line_id.attribute_id.id] = attribute_line_id.value_ids.ids

                    key = str(attribute_line_id.attribute_id.id) + '-' + '-'.join([str(p.id) for p in attribute_line_id.value_ids])
                    if key not in default_code_dict:
                        default_code_dict[key] = child_product_id.default_code

            print("\n +++++ default_code_dict ++++++", default_code_dict)
            print("\n +++++ attributes_dict ++++++", attributes_dict)

            exists_product_id = self.env['product.product'].search([
                ('default_code', '=', main_product.default_code),
                ('id', '!=', main_product.id)
            ])
            if exists_product_id:
                print("\n ++++++ exists_product_id +++++++", exists_product_id, exists_product_id.product_tmpl_id)
                exists_product_id = exists_product_id[0]
                product_template_id = exists_product_id.product_tmpl_id
                attribute_line_list = []
                
                # ----------------------- Brand Attribute -------------------------
                exists_brand_attribute_line_id = exists_product_id.product_tmpl_id.attribute_line_ids.filtered(
                    lambda x: x.attribute_id.id == 6
                )
                if exists_brand_attribute_line_id and 19 not in exists_brand_attribute_line_id.value_ids.ids:
                    exists_brand_attribute_line_id.write({
                        'value_ids': [(4, 19)]
                    })
                elif not exists_brand_attribute_line_id:
                    attribute_line_list.append((0, 0, {
                        'attribute_id': 6,
                        'value_ids': [(6, 0, [19])],
                    }))
                # ----------------------- Brand Attribute -------------------------
                
                # ----------------------- Bundle Attribute -------------------------
                exists_bundle_attribute_line_id = exists_product_id.product_tmpl_id.attribute_line_ids.filtered(
                    lambda x: x.attribute_id.id == 17
                )
                if exists_bundle_attribute_line_id:
                    for i in  [733, 734]:
                        if exists_bundle_attribute_line_id and i not in exists_bundle_attribute_line_id.value_ids.ids:
                            exists_bundle_attribute_line_id.write({
                                'value_ids': [(4, i)]
                            })
                else:
                    attribute_line_list.append((0, 0, {
                        'attribute_id': 17,
                        'value_ids': [(6, 0, [733, 734])],
                    }))
                # ----------------------- Bundle Attribute -------------------------
                for attribute_id in attributes_dict:
                    exists_attribute_line_id = exists_product_id.product_tmpl_id.attribute_line_ids.filtered(lambda x: x.attribute_id.id == attribute_id)
                    if exists_attribute_line_id:
                        for v in attributes_dict[attribute_id]:
                            if v not in exists_attribute_line_id.value_ids.ids:
                                print("\n ++++ attribute_id, attributes_dict[attribute_id] ++++", attribute_id, attributes_dict[attribute_id])
                                exists_attribute_line_id.write({
                                    'value_ids': [(4, v)]
                                })
                    elif not exists_attribute_line_id:
                        attribute_line_list.append((0, 0, {
                            'attribute_id': attribute_id,
                            'value_ids': [(6, 0, attributes_dict[attribute_id])],
                        }))
                print("\n +++++++ attribute_line_list +++++", attribute_line_list)
                main_product.product_tmpl_id.attribute_line_ids.unlink()
                child_product.mapped('product_tmpl_id').unlink()
                if attribute_line_list:
                    product_template_id.write({
                        'attribute_line_ids': attribute_line_list,
                    })
            else:
                attribute_line_list = [
                    (0,0,{
                        'attribute_id': 6,
                        'value_ids': [(6, 0, [19])],
                    }), (0,0,{
                        'attribute_id': 17,
                        'value_ids': [(6, 0, [733, 734])],
                    })
                ]

                for attribute_id in attributes_dict:
                    attribute_line_list.append((0,0,{
                        'attribute_id': attribute_id,
                        'value_ids': [(6, 0, attributes_dict[attribute_id])],
                    }))

                print("\n +++++++ attribute_line_list +++++++", attribute_line_list)
                default = {'name': main_product.product_tmpl_id.name}
                product_template_id = main_product.product_tmpl_id.copy(default=default)
                main_product.product_tmpl_id.attribute_line_ids.unlink()
                child_product.mapped('product_tmpl_id').unlink()
                product_template_id.attribute_line_ids.unlink()
                product_template_id.write({
                    'attribute_line_ids': attribute_line_list,
                })

            print("\n +++++++product_template_id.product_variant_ids +++++++ ", product_template_id.product_variant_ids)
            for product in product_template_id.product_variant_ids:
                pads_hose_key = ''
                main_key = ''
                for attribute_value_id in product.product_template_variant_value_ids:
                    print("\n ++++++ attribute_value_id ++++++", attribute_value_id.product_attribute_value_id)
                    key = str(attribute_value_id.attribute_id.id) + '-' + str(attribute_value_id.product_attribute_value_id.id)
                    if attribute_value_id.product_attribute_value_id.id == 733:
                        pads_hose_key = 'B'
                    print("\n +++++ key +++++", key)
                    if key in default_code_dict:
                        main_key = key
    
                if main_key in default_code_dict:
                    if pads_hose_key:
                        product.default_code = default_code_dict[main_key] + '-' + pads_hose_key
                    else:
                        product.default_code = default_code_dict[main_key]