/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.WebsiteProductDocumentPreview = publicWidget.Widget.extend({
    selector: "#product_documents",
    events: {
        "click .o_product_document_preview": "_onPreviewClick",
    },

    _onPreviewClick: function (ev) {
        const link = ev.currentTarget;
        if (link.dataset.previewable !== "true") {
            return;
        }

        ev.preventDefault();
        const url = link.getAttribute("href");
        const title = link.textContent.trim();
        this._openPreviewModal(url, title);
    },

    _openPreviewModal: function (url, title) {
        const modalId = "product_document_preview_modal";
        const titleId = `${modalId}_title`;
        const modal = document.createElement("div");
        modal.className = "modal fade";
        modal.id = modalId;
        modal.tabIndex = -1;
        modal.setAttribute("aria-hidden", "true");
        modal.setAttribute("aria-labelledby", titleId);

        modal.innerHTML = `
            <div class="modal-dialog modal-xl modal-dialog-centered" role="document" style="height: 90vh; max-width: 95vw;">
                <div class="modal-content" style="height: 100%;">
                    <div class="modal-header">
                        <h5 class="modal-title" id="${titleId}"></h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body p-0" style="flex: 1 1 auto; overflow: hidden;">
                        <iframe width="100%" height="100%" style="border: none;" title=""></iframe>
                    </div>
                </div>
            </div>
        `;

        modal.querySelector(".modal-title").textContent = title;
        const iframe = modal.querySelector("iframe");
        iframe.src = url;
        iframe.title = title;

        document.body.appendChild(modal);
        const $modal = $(modal);
        $modal.modal("show");
        $modal.on("hidden.bs.modal", function () {
            $(".modal-backdrop").remove();
            $modal.remove();
        });
    },
});
