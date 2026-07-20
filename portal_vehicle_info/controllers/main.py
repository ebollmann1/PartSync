# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http
from odoo.http import request
# from odoo.addons.http_routing.models.ir_http import slug
from odoo.addons.portal.controllers import portal
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website.models.ir_http import sitemap_qs2dom
from odoo.tools import SQL


class CustomerPortal(portal.CustomerPortal):

    def _get_model_ids(self, model, domain):
        """
        Returns a recordset of the given model filtered by the specified domain.

        :param model: Name of the Odoo model to search.
        :param domain: Domain filter used for searching records.
        :return: Sorted recordset of the matching records.
        """
        model_obj = request.env[model]
        ids = model_obj._search(domain)

        # Return sorted recordset
        return model_obj.browse(sorted(ids))

    @http.route('/save/vehicle_info', methods=['POST'], type='jsonrpc', auth='user')
    def save_vehicle_info(self, **kwargs):
        """
        Creates or updates vehicle information records from the frontend.

        Expected payload:
          - to_update: dict of record IDs with their updated values
          - to_create: list of new vehicle information dictionaries
        """
        # Update existing vehicle information records
        if 'to_update' in kwargs:
            for vehicle_info, vehicle_info_vals in kwargs.get('to_update', {}).items():
                request.env['vehicle.information'].sudo().browse(int(vehicle_info)).write(vehicle_info_vals)

        # Create new vehicle information records
        if 'to_create' in kwargs:
            for vehicle_info_vals in kwargs.get('to_create', []):
                vehicle_info_vals.update({
                    'partner_id': request.env.user.partner_id.id,
                })
            if kwargs.get('to_create', []):
                request.env['vehicle.information'].sudo().create(kwargs.get('to_create'))
        return True

    @http.route('/get/portal/vehicle_info', methods=['POST'], type='jsonrpc', auth='user')
    def get_portal_vehicle_info(self, **kwargs):
        """
        Retrieves filtered fitment (vehicle) data for the portal based on selected filters.

        :param kwargs: Filter parameters like 'make', 'year', and 'model'
        :return: Dictionary containing available make, year, model, submodel, and rear_wheels options
        """
        fitment_ids = self._get_model_ids('fitment.master', [])
        make_ids, year_ids, model_ids, submodel_ids, rear_wheels_ids = request.env['fitment.master'], request.env['fitment.master'], request.env['fitment.master'], request.env['fitment.master'], request.env['fitment.master']
        make_data, year_data, model_data = kwargs.get('make', False), kwargs.get('year', False), kwargs.get('model', False)

        # Filter based on selected make/year/model combinations
        if make_data and year_data and model_data:
            submodel_ids = fitment_ids.filtered(lambda f: f.year_id and f.year_id.name == year_data and f.model_id and f.model_id.name == model_data and f.make_id and f.make_id.name == make_data)
            rear_wheels_ids = fitment_ids.filtered(lambda f: f.year_id and f.year_id.name == year_data and f.model_id and f.model_id.name == model_data and f.make_id and f.make_id.name == make_data)
            model_ids = fitment_ids.filtered(lambda f: f.year_id and f.year_id.name == year_data and f.make_id and f.make_id.name == make_data)
            make_ids = fitment_ids.filtered(lambda f: f.year_id and f.year_id.name == year_data)
            year_ids = fitment_ids.filtered(lambda f: f.make_id and f.make_id.name == make_data)
        elif make_data and year_data and not model_data:
            model_ids = fitment_ids.filtered(lambda f: f.year_id and f.year_id.name == year_data and f.make_id and f.make_id.name == make_data)
            make_ids = fitment_ids.filtered(lambda f: f.year_id and f.year_id.name == year_data)
            year_ids = fitment_ids.filtered(lambda f: f.make_id and f.make_id.name == make_data)
        elif make_data and not year_data and not model_data:
            model_ids = fitment_ids.filtered(lambda f: f.make_id and f.make_id.name == make_data)
            make_ids = fitment_ids
            year_ids = fitment_ids.filtered(lambda f: f.make_id and f.make_id.name == make_data)
        elif not make_data and year_data and not model_data:
            model_ids = fitment_ids.filtered(lambda f: f.year_id and f.year_id.name == year_data)
            make_ids = fitment_ids.filtered(lambda f: f.year_id and f.year_id.name == year_data)
            year_ids = fitment_ids

        # Extract and clean field values
        make_ids, model_ids, year_ids, submodel_ids = list(filter(bool, make_ids.mapped('make_id.name'))), list(filter(bool, model_ids.mapped('model_id.name'))), list(filter(bool, year_ids.mapped('year_id.name'))), list(filter(bool, submodel_ids.mapped('submodel_id.name')))
        rear_wheels_ids = list(filter(bool, rear_wheels_ids.mapped('rear_wheels_id.name')))
        data = {
            'make': list(set(make_ids)),
            'year': list(set(year_ids)),
            'model': list(set(model_ids)),
            'submodel': list(set(submodel_ids)),
            'rear_wheels': list(set(rear_wheels_ids))
        }
        data['make'].sort()
        data['year'].sort()
        data['model'].sort()
        data['submodel'].sort()
        data['rear_wheels'].sort()
        return data

    @http.route('/deactivate/vehicle_info', methods=['POST'], type='jsonrpc', auth='user')
    def deactivate_vehicle_info(self, **kwargs):
        """
        Deactivates (archives) a vehicle information record from the portal.

        :param vehicle_info_id: ID of the vehicle information record to deactivate
        """
        if 'vehicle_info_id' in kwargs:
            if request.env['vehicle.information'].sudo().browse(kwargs.get('vehicle_info_id')):
                request.env['vehicle.information'].sudo().browse(kwargs.get('vehicle_info_id')).write({'active': False})
        return True

    def _prepare_home_portal_values(self, counters):
        """
        Extends portal home values with the count of active vehicle information records.
        """
        values = super()._prepare_home_portal_values(counters)
        if 'vehicle_info_count' in counters:
            partner_id = request.env.user.partner_id
            values['vehicle_info_count'] = len(partner_id.vehicle_info_ids.ids) or 1

        # Disable vehicle info counter if sync is turned off in configuration
        partsync_customer_vehicle = request.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_customer_vehicle')
        if not partsync_customer_vehicle:
            values['vehicle_info_count'] = 0
        return values

    @http.route(['/my/vehicle_info'], type='http', auth="user", website=True)
    def portal_vehicle_info(self, **kwargs):
        """
        Renders the 'My Vehicle Information' page in the website portal.

        This route displays the logged-in user's saved vehicle information along
        with available fitment options like make, year, model, submodel, and rear wheels.

        :param kwargs: Optional keyword arguments (not used directly here).
        :return: Rendered QWeb page for vehicle information.
        """
        # values = self._prepare_sale_portal_rendering_values(quotation_page=False, **kwargs)

        # Get current logged-in user's partner record
        partner = request.env.user.partner_id

        # Check if vehicle management feature is enabled in configuration
        partsync_customer_vehicle = request.env['ir.config_parameter'].sudo().get_param(
            'mmy_config.partsync_customer_vehicle')

        # Prepare values for template rendering
        values = {
            'page_name': 'vehicle',
            'vehicle_informations': partner.vehicle_info_ids,
            'partsync_customer_vehicle': partsync_customer_vehicle,
            'makes': request.env['vehicle.information'].get_make_value(),
            'years': request.env['vehicle.information'].get_year_value(),
            'models': request.env['vehicle.information'].get_model_value(),
            'submodels': request.env['vehicle.information'].get_submodel_value(),
            'rear_wheels': request.env['vehicle.information'].get_rear_wheels_value(),
        }
        # Render the portal page with prepared values
        return request.render("portal_vehicle_info.portal_vehicle_information", values)


class WebsiteSaleInherit(WebsiteSale):

    def sitemap_shop(env, rule, qs):
        if not qs or qs.lower() in '/shop':
            yield {'loc': '/shop'}

        Category = env['product.public.category']
        dom = sitemap_qs2dom(qs, '/shop/category', Category._rec_name)
        dom += env['website'].get_current_website().website_domain()
        slug = env['ir.http']._slug
        for cat in Category.search(dom):
            loc = '/shop/category/%s' % slug(cat)
            if not qs or qs.lower() in loc:
                yield {'loc': loc}

    @http.route([
        '/shop',
        '/shop/page/<int:page>',
        '/shop/category/<model("product.public.category"):category>',
        '/shop/category/<model("product.public.category"):category>/page/<int:page>',
    ], type='http', auth="public", website=True, sitemap=sitemap_shop)
    def shop(self, page=0, category=None, search='', min_price=0.0, max_price=0.0, ppg=False, **post):
        """
        Renders the shop page with optional vehicle-based filtering.

        This method extends the default `/shop` route to filter products
        based on the user's selected vehicle information.

        :param page: Current pagination page.
        :param category: Product category to filter by.
        :param search: Search query for products.
        :param min_price: Minimum price filter.
        :param max_price: Maximum price filter.
        :param ppg: Products per page.
        :param post: Additional POST data including user vehicle selection.
        :return: Rendered shop page with applied filters.
        """

        # If a user vehicle is selected, add its details to the filter
        if post.get('user_vehicles', False):
            user_vehicle_info = request.env['vehicle.information'].browse(int(post.get('user_vehicles')))
            post.update({
                'fitment_year': user_vehicle_info.year,
                'fitment_make': user_vehicle_info.make,
                'fitment_model': user_vehicle_info.model,
                'fitment_submodel': user_vehicle_info.submodel,
                'fitment_rear_wheels': user_vehicle_info.rear_wheels,
            })

        # Call the original shop method from WebsiteSale
        res = super(WebsiteSaleInherit, self).shop(
            page=page, category=category, search=search, min_price=min_price, max_price=max_price, ppg=ppg, **post)

        # Update the response context with selected vehicle info for frontend
        if post.get('user_vehicles', False):
            res.qcontext.update({
                'select_vehicle_info': int(post.get('user_vehicles')),
            })
        return res
