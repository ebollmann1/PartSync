/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";
import { session } from '@web/session';
import { rpc } from "@web/core/network/rpc";

publicWidget.registry.VehicleInformation = publicWidget.Widget.extend({
    selector: '.portal_vehicle_information',
    events: {
        'click .save_vehicle_info': '_onSaveVehicleInfo',
        'click .add_vehicle_info': '_onAddVehicleInfo',
        'click .delete_vehicle_info': '_onDeleteVehicleInfo',
        'change .vehicle_make, .vehicle_year, .vehicle_model' : '_onchangemake',
    },

//    init() {
//        this._super(...arguments);
//        this.rpc = this.bindService("rpc");
//    },

    _onchangemake: async function(ev){
        var self = this;
        var $curr_row = $(ev.currentTarget).parents('tr');
        var data = {
            'make':$curr_row.find('select.vehicle_make').val(),
            'model':$curr_row.find('select.vehicle_model').val(),
            'year':$curr_row.find('select.vehicle_year').val(),
            'submodel':$curr_row.find('select.vehicle_submodel').val(),
            'rear_wheels':$curr_row.find('select.vehicle_rear_wheels').val()}
//        const res = await this.rpc('/get/portal/vehicle_info', data);
        const res = await rpc('/get/portal/vehicle_info', data);
        let years = res['year'];
        var $vyear_ele = $curr_row.find('select.vehicle_year').empty()
        var $vmake_ele = $curr_row.find('select.vehicle_make').empty()
        var $vmodel_ele = $curr_row.find('select.vehicle_model').empty()
        var $vsubmodel_ele = $curr_row.find('select.vehicle_submodel').empty()
        var $vrear_wheels_ele = $curr_row.find('select.vehicle_rear_wheels').empty()

        res['year'].forEach((year_id) => {
            var option = "<option value='"+year_id+"'>"+year_id+"</option>"
            $vyear_ele.append(option)
        });

        res['make'].forEach((make_id) => {
            var option = "<option value='"+make_id+"'>"+make_id+"</option>"
            $vmake_ele.append(option)
        });

        res['model'].forEach((model_id) => {
            var option = "<option value='"+model_id+"'>"+model_id+"</option>"
            $vmodel_ele.append(option)
        });

        res['submodel'].forEach((submodel_id) => {
            var option = "<option value='"+submodel_id+"'>"+submodel_id+"</option>"
            $vsubmodel_ele.append(option)
        });

        res['rear_wheels'].forEach((rear_wheels_id) => {
            var option = "<option value='"+rear_wheels_id+"'>"+rear_wheels_id+"</option>"
            $vrear_wheels_ele.append(option)
        });

        $vyear_ele.val(data['year'])
        $vmake_ele.val(data['make'])
        $vmodel_ele.val(data['model'])
        $vsubmodel_ele.val(data['submodel'])
        $vrear_wheels_ele.val(data['rear_wheels'])
        if (data['year'] && data['make']){
            $vmodel_ele.removeAttr('disabled')
        };
        if (data['year'] && data['make'] && data['model']){
            $vsubmodel_ele.removeAttr('disabled')
            $vrear_wheels_ele.removeAttr('disabled')
        };
    },

    _onSaveVehicleInfo: async function(ev){
        var vehicle_infos = $('tr.vehicle_info_ids').toArray();
        var values_to_update = {}
        var values_to_create = []

        vehicle_infos.forEach((vehicle_info) => {
            console.log("\n +++++++ ", $(vehicle_info).attr('id'))
            if ($(vehicle_info).attr('id')) {
                values_to_update[$(vehicle_info).attr('id')] = {
                    'tag': $(vehicle_info).find('input[class="vehicle_tag"]').val(),
                    'state': $(vehicle_info).find('input[class="vehicle_state"]').val(),
                    'mileage': $(vehicle_info).find('input[class="vehicle_mileage"]').val(),
                    'year': $(vehicle_info).find('select[class="vehicle_year"]').val(),
                    'make': $(vehicle_info).find('select[class="vehicle_make"]').val(),
                    'model': $(vehicle_info).find('select[class="vehicle_model"]').val(),
                    'submodel': $(vehicle_info).find('select[class="vehicle_submodel"]').val(),
                    'rear_wheels': $(vehicle_info).find('select[class="vehicle_rear_wheels"]').val(),
                }
            } else {
                values_to_create.push({
                    'tag': $(vehicle_info).find('input[class="vehicle_tag"]').val(),
                    'state': $(vehicle_info).find('input[class="vehicle_state"]').val(),
                    'mileage': $(vehicle_info).find('input[class="vehicle_mileage"]').val(),
                    'year': $(vehicle_info).find('select[class="vehicle_year"]').val(),
                    'make': $(vehicle_info).find('select[class="vehicle_make"]').val(),
                    'model': $(vehicle_info).find('select[class="vehicle_model"]').val(),
                    'submodel': $(vehicle_info).find('select[class="vehicle_submodel"]').val(),
                    'rear_wheels': $(vehicle_info).find('select[class="vehicle_rear_wheels"]').val(),
                });
            };
        });
//        await this.rpc('/save/vehicle_info', {'to_create': values_to_create, 'to_update': values_to_update});
        await rpc('/save/vehicle_info', {'to_create': values_to_create, 'to_update': values_to_update});
        window.location.reload();
    },

    _onAddVehicleInfo: function(ev){
        $('center.no_vehicle_found_message').addClass('d-none');
        var self = this;
        var $table = $('div.portal_vehicle_information table');
        var $tr = $('<tr class="vehicle_info_ids"></tr>')
        var $td_vehicle_tag = $('<td><input type="text" class="vehicle_tag" style="border-radius: 5px;width: 130px;"/></td>')
        var $td_vehicle_state = $('<td><input type="text" class="vehicle_state" style="border-radius: 5px;width: 130px;"/></td>')
        var $td_vehicle_mileage = $('<td><input type="text" class="vehicle_mileage" style="border-radius: 5px;width: 130px;"/></td>')
        var $td_vehicle_year = $('<td><select id="vehicle_year" class="vehicle_year" style="border-radius: 5px;width: 130px;"></td>')
        var $td_vehicle_make = $('<td><select id="vehicle_make" class="vehicle_make" style="border-radius: 5px;width: 130px;"></td>')
        var $td_vehicle_model = $('<td><select id="vehicle_model" class="vehicle_model" style="border-radius: 5px;width: 130px;" disabled="disabled"></td>')
        var $td_vehicle_submodel = $('<td><select id="vehicle_submodel" class="vehicle_submodel" style="border-radius: 5px;width: 130px;" disabled="disabled"></td>')
        var $td_vehicle_rear_wheels = $('<td><select id="vehicle_rear_wheels" class="vehicle_rear_wheels" style="border-radius: 5px;width: 130px;" disabled="disabled"></td>')
        var $vehicle_count = parseInt($('span.vehicle_count').text());
        var $td_vehicle_count = $('<td>' + $vehicle_count.toString() + '</td>');
        $('span.vehicle_count').text($vehicle_count + 1);
        
        var $vehicle_make_option = $('<option value="">Select Make</option>' )
        $td_vehicle_make.find('select').append($vehicle_make_option);
        session.makes.forEach((make_value) => {
            var $option = $('<option value="' + make_value[0] + '">' + make_value[1] + "</option>" )
            $td_vehicle_make.find('select').append($option);
        });

        var $vehicle_model_option = $('<option value="">Select Model</option>' )
        $td_vehicle_model.find('select').append($vehicle_model_option);
        session.models.forEach((model_value) => {
            var $option = $('<option value="' + model_value[0] + '">' + model_value[1] + "</option>" )
            $td_vehicle_model.find('select').append($option);
        });

        var $vehicle_year_option = $('<option value="">Select Year</option>' )
        $td_vehicle_year.find('select').append($vehicle_year_option);
        session.years.forEach((year_value) => {
            var $option = $('<option value="' + year_value[0] + '">' + year_value[1] + "</option>" )
            $td_vehicle_year.find('select').append($option);
        });

        var $vehicle_submodel_option = $('<option value="">Select Submodel</option>' )
        $td_vehicle_submodel.find('select').append($vehicle_submodel_option);
        session.submodels.forEach((submodel_value) => {
            var $option = $('<option value="' + submodel_value[0] + '">' + submodel_value[1] + "</option>" )
            $td_vehicle_submodel.find('select').append($option);
        });

        var $vehicle_rear_wheels_option = $('<option value="">Select Wheel Configuration</option>' )
        $td_vehicle_rear_wheels.find('select').append($vehicle_rear_wheels_option);
        session.rear_wheels.forEach((rear_wheels_value) => {
            var $option = $('<option value="' + rear_wheels_value[0] + '">' + rear_wheels_value[1] + "</option>" )
            $td_vehicle_rear_wheels.find('select').append($option);
        });

        $tr.append($td_vehicle_count);
        $tr.append($td_vehicle_tag);
        $tr.append($td_vehicle_state);
        $tr.append($td_vehicle_mileage);
        $tr.append($td_vehicle_make);
        $tr.append($td_vehicle_model);
        $tr.append($td_vehicle_year);
        $tr.append($td_vehicle_submodel);
        $tr.append($td_vehicle_rear_wheels);

        var $deletevehicleinfo = $('<td><i class="fa fa-trash delete_vehicle_info" style="cursor:pointer;"/></td>');
        $deletevehicleinfo.find('i').click(function(ev){
            self._onDeleteVehicleInfo(ev)
        });
        $tr.append($deletevehicleinfo);
        $table.append($tr);
    },

    _onDeleteVehicleInfo: async function(ev){
        var vehicle_info_id = $(ev.currentTarget).attr('id');
        if (vehicle_info_id){
//            const res = await this.rpc('/deactivate/vehicle_info', {'vehicle_info_id': parseInt(vehicle_info_id)})
            const res = await rpc('/deactivate/vehicle_info', {'vehicle_info_id': parseInt(vehicle_info_id)})
            if (res) {
                window.location.reload();
            };
        } else {
            $(ev.currentTarget).parent().parent().remove();
            if ($('div.portal_vehicle_information table tr.vehicle_info_ids').length == 0){
                $('center.no_vehicle_found_message').removeClass('d-none');
            }
            var vehicle_infos = $('tr.vehicle_info_ids').toArray();;
            var values_to_update = {}
            var values_to_create = []
            var count = 1
            vehicle_infos.forEach((vehicle_info) => {
                $($(vehicle_info).find('td')[0]).text(count.toString())
                count += 1
            });
            $('span.vehicle_count').text(count);
        };
    },
});
