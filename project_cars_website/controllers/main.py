# -*- coding: utf-8 -*-

from odoo import http
from odoo.tools import lazy
from odoo.http import request, route
from odoo.addons.website_sale.controllers.main import WebsiteSale, TableCompute
from odoo.addons.website.controllers.form import WebsiteForm
from odoo.addons.website.models.ir_http import sitemap_qs2dom
from odoo.tools import SQL
from odoo.tools.translate import LazyTranslate
from werkzeug.exceptions import NotFound
from odoo.addons.website_sale.const import SHOP_PATH

_lt = LazyTranslate(__name__)

# from odoo.addons.http_routing.models.ir_http import slug


class WebsiteForm(WebsiteForm):

    # Check and insert values from the form on the model <model>
    @http.route('/website/form/<string:model_name>', type='http', auth="public", methods=['POST'], website=True, csrf=False)
    def website_form(self, model_name, **kwargs):
        """
        This method handles website form submissions — it removes extra tokens, checks for duplicate emails,
        creates a new partner record if needed, and updates missing email fields before returning the response.
        """
        if 'recaptcha_token_response' in kwargs:
            kwargs.pop('recaptcha_token_response')
        if 'csrf_token' in kwargs:
            kwargs.pop('csrf_token')
        partner_id = request.env['res.partner'].sudo().search([('email', '=', str(kwargs.get('email')))])
        if partner_id:
            return '{"error": "Email is already registered.", "error_fields": "contact3"}'
        res = super(WebsiteForm, self).website_form(model_name, **kwargs)
        if kwargs:
            kwargs.update({
                'email': kwargs.get('email'),
            })
            p_id = self._handle_website_form('res.partner', **kwargs)
            p_id = p_id and eval(p_id) or False
            if p_id and p_id.get('id'):
                partner_id = request.env['res.partner'].sudo().browse(p_id['id'])
                if partner_id and not partner_id.email:
                    partner_id.email = kwargs.get('email')
        return res

    @http.route('/get_more_product_information', type='http', auth='public', website=True)
    def product_information(self, **post):
        """
        This method is used to fetch product information and display it in the rendered template.
        """
        value = {
            'product_name': post.get('product_name'),
            'product_id': post.get('product_id'),
            'return_url': post.get('return_url'),
        }
        return request.render('project_cars_website.get_more_product_information_page', value)

class WebsiteSale(WebsiteSale):

    def sitemap_shop(env, rule, qs):
        """
        This method generates sitemap entries for the /shop and /shop/category URLs.
        It adds the main shop page and all public product categories to the sitemap,
        helping search engines index shop and category pages properly.
        """
        if not qs or qs.lower() in '/shop':
            yield {'loc': '/shop'}

        Category = env['product.public.category']
        dom = sitemap_qs2dom(qs, '/shop/category', Category._rec_name)
        dom += env['website'].get_current_website().website_domain()
        slug = request.env['ir.http']._slug
        for cat in Category.search(dom):
            loc = '/shop/category/%s' % slug(cat)
            if not qs or qs.lower() in loc:
                yield {'loc': loc}

    def _shop_get_query_url_kwargs(self,search, min_price, max_price,order=None, tags=None, **post):
        """
        This method extends the base shop query parameters to include custom fitment fields
        (make, model, year, submodel, rear wheels, and vehicle platform) so they persist
        across pagination and filtering on the shop page.
        """
        res = super(WebsiteSale, self)._shop_get_query_url_kwargs(
            search=search, min_price=min_price, max_price=max_price, order=order, tags=tags, **post
        )
        res.update({
            'fitment_make': post.get('fitment_make', ''),
            'fitment_year': post.get('fitment_year', ''),
            'fitment_model': post.get('fitment_model', ''),
            'fitment_submodel': post.get('fitment_submodel', ''),
            'fitment_rear_wheels': post.get('fitment_rear_wheels', ''),
            'vehicle_platform_id': post.get('vehicle_platform_id', ''),
        })
        return res

    def _get_model_ids(self, model, domain):
        """
        This method searches for records in the given model based on the provided domain and returns a sorted recordset.
        """
        model_obj = request.env[model]
        ids = model_obj._search(domain)

        # Return sorted recordset
        return model_obj.browse(sorted(ids))

    @route(
        [
            SHOP_PATH,
            f'{SHOP_PATH}/page/<int:page>',
            f'{SHOP_PATH}/category/<model("product.public.category"):category>',
            f'{SHOP_PATH}/category/<model("product.public.category"):category>/page/<int:page>',
        ],
        type='http',
        auth='public',
        website=True,
        list_as_website_content=_lt("Shop"),
        sitemap=sitemap_shop,
        # Sends a 404 error in case of any Access error instead of 403.
        handle_params_access_error=lambda e, **kwargs: NotFound.code,
    )
    def shop(self, page=0, category=None, search='', min_price=0.0, max_price=0.0, tags='', **post):
    # def shop(self, page=0, category=None, search='', min_price=0.0, max_price=0.0, ppg=False, **post):
        """
        Extends the default Odoo shop route to implement advanced product filtering based on fitment criteria:
        Make, Model, Year, Submodel, Rear Wheels, and Vehicle Platform.
        Handles product domains, pagination, attributes, and pricing context for website display.
        """
        # Call the original shop method and get the base response
        # res = super(WebsiteSale, self).shop(
        #     page=page, category=category, search=search, min_price=min_price, max_price=max_price, ppg=ppg, **post)
        res = super(WebsiteSale, self).shop(
            page=page, category=category, search=search, min_price=min_price, max_price=max_price, tags=tags, **post)

        # Get current website and base URL
        url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        website = request.env['website'].get_current_website()

        # Update context with selected fitment options from the request
        res.qcontext.update({
            'url': url,
            'select_fitment_year': post.get('fitment_year', ''),
            'select_fitment_make': post.get('fitment_make', ''),
            'select_fitment_model': post.get('fitment_model', ''),
            'select_fitment_submodel': post.get('fitment_submodel', ''),
            'select_fitment_rear_wheels': post.get('fitment_rear_wheels', ''),
            'select_vehicle_platform_id': post.get('vehicle_platform_id', ''),
        })

        # Default products per page
        # ppg = ppg and ppg or 20
        ppg = website.shop_ppg or 20
        fitment_data = {'year': [], 'make': [], 'model': [], 'submodel': [], 'rear_wheels': [], 'vehicle_platform_id': []}
        domain = []

        # If make is missing, clear make-dependent fields including model
        if not post.get('fitment_make'):
            post['fitment_model'] = None
            post['fitment_year'] = None
            post['fitment_submodel'] = None
            post['fitment_rear_wheels'] = None
            post['vehicle_platform_id'] = None
        else:
            # Only add make if provided
            domain.append(('make_id.name', '=', post.get('fitment_make')))

        # If model is missing or make changed, clear model-dependent fields
        if post.get('fitment_make') and post.get('fitment_model'):
            domain.append(('model_id.name', '=', post.get('fitment_model')))

        # Only add year if model exists
        if post.get('fitment_make') and post.get('fitment_year'):
            domain.append(('year_id.name', '=', post.get('fitment_year')))

        # Only add submodel if model exists
        if post.get('fitment_make') and post.get('fitment_submodel'):
            domain.append(('submodel_id.name', '=', post.get('fitment_submodel')))

        # Only add rear wheels if model exists
        if post.get('fitment_make') and post.get('fitment_rear_wheels'):
            domain.append(('rear_wheels_id.name', '=', post.get('fitment_rear_wheels')))

        # Vehicle platform depends on model
        if post.get('fitment_make') and post.get('vehicle_platform_id'):
            domain.append(('vehicle_platform_id.name', '=', post.get('vehicle_platform_id')))

        selected_product = []

        # Search for products that match the fitment domain
        if domain:
            fitment_ids = self._get_model_ids('fitment.master', domain)
            if category:
                customer_product_ids = request.env['customer.product.master'].search([
                    ('fitment_ids', 'in', fitment_ids.ids),
                '|',('product_id.company_id', '=', False), ('product_id.company_id', '=', website.company_id.id),
                    ('product_id.public_categ_ids', 'child_of', int(category))])
            else:
                customer_product_ids = request.env['customer.product.master'].search([
                    ('fitment_ids', 'in', fitment_ids.ids),
                '|',('product_id.company_id', '=', False), ('product_id.company_id', '=', website.company_id.id)])

            selected_product = customer_product_ids.mapped('product_id').ids

        # Handle search by text
        if search:
            selected_product = res.qcontext.get('search_product').mapped('product_variant_ids').ids

        # Narrow down by category
        if not domain and category:
            pro_ids = res.qcontext.get('products').mapped('product_variant_ids')
            selected_product = list(set(selected_product) & set(pro_ids.ids))

        # Filter attributes if applicable
        if res.qcontext.get('search_product') and res.qcontext.get('attrib_values'):
            pro_ids = res.qcontext.get('search_product').mapped('product_variant_ids')
            selected_product = list(set(selected_product) & set(pro_ids.ids))

        ppr = website.shop_ppr or 4

        # Load products and attributes for the selected variants
        if selected_product:
            products = request.env['product.product'].browse(selected_product).mapped('product_tmpl_id')
            shop_url = "/shop"

            ProductAttribute = request.env['product.attribute']
            attribute_filter_domain = [('id', 'in', products.ids)]
            slug = request.env['ir.http']._slug
            if category:
                shop_url = "/shop/category/%s" % slug(category)
                attribute_filter_domain.append(('public_categ_ids', 'child_of', int(category)))

            categories_filtered_products = self._get_model_ids('product.template', attribute_filter_domain)
            filteres_attributes = lazy(lambda: ProductAttribute.search([
                ('product_tmpl_ids', 'in', categories_filtered_products.ids),
                ('visibility', '=', 'visible'),
            ]))

            product_count = products and len(products) or 0
            pager = website.pager(url=shop_url, total=product_count, page=page, step=ppg, scope=7, url_args=post)
            offset = pager['offset']
            products = products[offset:offset + ppg]
            products.fetch()

            variants = request.env['product.product'].sudo().browse(
                product._get_first_possible_variant_id() for product in products)
            variants.fetch()
            product_variants = dict(zip(products, variants))

            res.qcontext.update({
                'products': products,
                'product_variants': product_variants,
                'search_count': product_count,  # common for all searchbox
                'bins': lazy(lambda: TableCompute().process(products, ppg, ppr)),
                'ppg': ppg,
                'ppr': ppr,
                'pager': pager,
                'attributes': filteres_attributes,
                'attribute_values': categories_filtered_products.mapped('attribute_line_ids').mapped('value_ids').filtered(lambda r: r.attribute_id in filteres_attributes)
            })

        # Handle case where domain exists but no products found
        if domain and not selected_product:
            pager = website.pager(url=url, total=0, page=page, step=ppg, scope=7, url_args=post)
            products = []
            res.qcontext.update({
                'products': False,
                'search_count': 0,  # common for all searchbox
                'bins': lazy(lambda: TableCompute().process(products, ppg, ppr)),
                'ppg': ppg,
                'ppr': ppr,
                'pager':pager
            })

        # Default product handling if no domain
        if not domain:
            product_count = res.qcontext.get('search_product') and len(res.qcontext.get('search_product').ids) or res.qcontext.get('products') and len(res.qcontext.get('products')) or 0
            pager = website.pager(url=url, total=product_count, page=page, step=ppg, scope=7, url_args=post)
            search_product = res.qcontext.get('search_product')
            offset = pager['offset']
            products = search_product[offset:offset + ppg]
            products.fetch()

            variants = request.env['product.product'].sudo().browse(
                product._get_first_possible_variant_id() for product in products)
            variants.fetch()
            product_variants = dict(zip(products, variants))

            res.qcontext.update({
                'products': products,
                'product_variants': product_variants,
                'all_products': search_product,
                'search_product': search_product,
                'search_count': product_count,
                'bins': lazy(lambda: TableCompute().process(products, ppg, ppr)),
                'ppg': ppg,
                'ppr': ppr
            })

        # Collect customer product master IDs
        search_products = selected_product
        if not search_products:
            search_products = res.qcontext.get('search_product').mapped('product_variant_ids').ids

        customer_product_ids = request.env['product.product'].browse(search_products).mapped('customer_product_master_ids')

        # Build fitment data for filtering
        fitment_make_ids = self._get_model_ids('fitment.master', [])
        if customer_product_ids:
            fitment_make_ids = self._get_model_ids('fitment.master', [
                ('id', 'in', customer_product_ids.mapped('fitment_ids').ids)
            ])
        # else:
        #     fitment_make_ids = self._get_model_ids('fitment.master', [])

            fitment_data['make'] = sorted(list(set(fitment_make_ids.mapped('make_id.name'))))
        else:
            fitment_data['make'] = []
        
        FITMENT_FIELDS = {
            'model': ['make', 'year', 'submodel', 'rear_wheels'],
            'year': ['make', 'model', 'submodel', 'rear_wheels'],
            'submodel': ['make', 'model', 'year', 'rear_wheels'],
            'rear_wheels': ['make', 'model', 'year', 'submodel'],
            'vehicle_platform_id': ['year', 'make', 'model', 'submodel', 'rear_wheels'],
        }

        RELATION_MAP = {
            'make': 'make_id.name',
            'model': 'model_id.name',
            'year': 'year_id.name',
            'submodel': 'submodel_id.name',
            'rear_wheels': 'rear_wheels_id.name',
            'vehicle_platform_id': 'vehicle_platform_id.name',
        }

        all_fitment_ids = customer_product_ids.mapped('fitment_ids').ids

        # Populate fitment dropdowns dynamically
        for key, dependencies in FITMENT_FIELDS.items():
            # skip some fields if model not selected
            if not post.get('fitment_make') and key in ['model','submodel', 'year', 'rear_wheels']:
                fitment_data[key] = []
                continue

            domain = [('id', 'in', all_fitment_ids)]
            for dep in dependencies:
                post_key = f'fitment_{dep}'
                if post.get(post_key):
                    domain.append((RELATION_MAP[dep], '=', post[post_key]))

            fitment_ids = self._get_model_ids('fitment.master', domain)
            fitment_data[key] = sorted(list(set(fitment_ids.mapped(RELATION_MAP[key]))))
        res.qcontext.update({
            'fitment_data': fitment_data,
        })

        # Whenever Make,Model,Year is not selected, attributes are filtered from here
        if not selected_product and category:
            ProductAttribute = request.env['product.attribute']
            attribute_filter_domain = [('public_categ_ids', 'child_of', int(category))]
            categories_filtered_products = request.env['product.template'].sudo().search(attribute_filter_domain)
            filteres_attributes = lazy(lambda: ProductAttribute.search([
                ('product_tmpl_ids', 'in', categories_filtered_products.ids),
                ('visibility', '=', 'visible'),
            ]))
            res.qcontext.update({
                'attributes': filteres_attributes,
                'attribute_values': categories_filtered_products.mapped('attribute_line_ids').mapped(
                    'value_ids').filtered(lambda r: r.attribute_id in filteres_attributes)
            })

        # fiscal_position_sudo = website.fiscal_position_id.sudo()

        # Update product prices in context
        products_prices = lazy(lambda: res.qcontext.get('products')._get_sales_prices(website))
        res.qcontext.update({
            'products_prices': products_prices,
            'get_product_prices': lambda product: lazy(lambda: products_prices[product.id])
        })
        return res

    @http.route(['/get/product_categories'], type='jsonrpc', auth="public", methods=['POST'])
    def get_product_categories(self, **kw):
        """
        Fetch product categories for the website shop.
        If a search term is provided ('search_categ_name'), it filters categories by name.
        Returns a list containing the category data and the search term.
        """
        domain = [
            ('product_tmpl_ids', '!=', False),
        ]
        if kw.get('search_categ_name'):
            domain.append(('name', 'ilike', kw.get('search_categ_name')))
        ecommerce_categ_ids = request.env['product.public.category'].search(domain)
        slug = request.env['ir.http']._slug
        ecommerce_categs = []
        for ecommerce_categ in ecommerce_categ_ids:
            cat_url = '/shop/category/%s' % slug(ecommerce_categ)
            ecommerce_categs.append({
                'id': ecommerce_categ.id,
                'name': ecommerce_categ.name,
                'display_name': ecommerce_categ.display_name,
                'url': cat_url,
                'product_count': len(ecommerce_categ.product_tmpl_ids.ids),
            })
        return [ecommerce_categs, kw.get('search_categ_name')]

    def _prepare_product_values(self, product, category, **kwargs):
        """Override to safely handle empty attribute_values."""
        attribute_values = kwargs.get('attribute_values')
        if attribute_values:
            # 🧹 Clean invalid / empty values
            attribute_value_ids = {int(i) for i in attribute_values.split(',') if i}
            kwargs['attribute_values'] = ','.join(str(i) for i in attribute_value_ids)
        # then call the parent
        return super()._prepare_product_values(product, category, **kwargs)

