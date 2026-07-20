/** @odoo-module **/
import VariantMixin from "@website_sale/js/variant_mixin";

const oldOnChangeCombination = VariantMixin._onChangeCombination;


VariantMixin._onChangeCombination = function (ev, parent, combination) {
    const $default_code = $(parent).find("span.default_code");
    $default_code.text(combination['default_code']);

    const $kit_div = $("div#kit_div");
    const $tbody = $("tbody#kit_table_ebody");
    const $save_price = $("span#save_price");
    const $final_total = $("td#final_total");
    const $tfoot = $("#kit_table_tfoot");
    const $fitment_div = $("div#fitment_data_div");
    const $fitment_tbody = $("tbody#fitment_data_table_ebody");
    const $product_height = $("td#product_height");
    const $product_width = $("td#product_width");
    const $product_length = $("td#product_length");
    const $weight = $("td#weight");
    const $volume = $("td#volume");

    var mrp_data;
    var content = '';
    for (var i=0; i< combination['mrp_data_count']; i++ ){
        mrp_data = combination['mrp_data'][i]
        content += '<tr>'
        content += '<td>'+mrp_data['component']+'</td>'
        content += '<td>'+mrp_data['quantity']+'</td>'
        content += '<td>'+mrp_data['unit']+'</td>'
        //content += '<td>'+mrp_data['list_price']+'</td>'
        //content += '<td>'+mrp_data['total']+'</td>'
        content += '</tr>'
    }
    if (combination['mrp_data_count'] > 0){
        $save_price.html(combination['save_price']);
        $final_total.html(combination['final_total']);
        $tbody.html(content);
        $kit_div.css('display', '')
        $kit_div.removeClass("o_hidden");
        $tfoot.removeClass("o_hidden");
    } else {
        $kit_div.addClass("o_hidden");
        $tfoot.addClass("o_hidden");
        $kit_div.css('display', 'none')
    }

    var fitment_data;
    var fitment_content = '';
    for (var i=0; i< combination['fitment_data_count']; i++ ){
        fitment_data = combination['fitment_data'][i]
        fitment_content += '<tr>'
        if (fitment_data['year']){
            fitment_content += '<td>'+fitment_data['year']+'</td>'
        } else {
            fitment_content += '<td>'+''+'</td>'
        }
        if (fitment_data['make']){
            fitment_content += '<td>'+fitment_data['make']+'</td>'
        } else {
            fitment_content += '<td>'+''+'</td>'
        }
        if (fitment_data['model']){
            fitment_content += '<td>'+fitment_data['model']+'</td>'
        } else {
            fitment_content += '<td>'+''+'</td>'
        }
        if (fitment_data['submodel']){
            fitment_content += '<td>'+fitment_data['submodel']+'</td>'
        } else {
            fitment_content += '<td>'+''+'</td>'
        }
        if (fitment_data['rear_wheels']){
            fitment_content += '<td>'+fitment_data['rear_wheels']+'</td>'
        } else {
            fitment_content += '<td>'+''+'</td>'
        }
        if (fitment_data['vehicle_platform']){
            fitment_content += '<td>'+fitment_data['vehicle_platform']+'</td>'
        } else {
            fitment_content += '<td>'+''+'</td>'
        }
        fitment_content += '</tr>'
    }
    if (combination['fitment_data_count'] > 0){
        $fitment_tbody.html(fitment_content);
        $fitment_div.css('display', '')
        $fitment_div.removeClass("o_hidden");
    } else {
        $fitment_div.addClass("o_hidden");
        $fitment_div.css('display', 'none')
    }
    if (combination['product_package_info'] ){
        $product_height.html(combination['product_package_info']['product_height']);
        $product_width.html(combination['product_package_info']['product_width']);
        $product_length.html(combination['product_package_info']['product_length']);
        $weight.html(combination['product_package_info']['weight'] + ' '+ combination['product_package_info']['weight_uom_name']);
        $volume.html(combination['product_package_info']['volume']+ ' '+ combination['product_package_info']['volume_uom_name']);
    }
    return oldOnChangeCombination.apply(this, arguments);
};
