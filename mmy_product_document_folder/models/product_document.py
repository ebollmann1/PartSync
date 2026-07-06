from odoo import api, fields, models


class ProductDocument(models.Model):
    _inherit = 'product.document'

    document_folder_id = fields.Many2one(
        'documents.document',
        string="Documents Folder",
        domain="[('type', '=', 'folder')]",
        compute='_compute_document_folder_id',
        inverse='_inverse_document_folder_id',
        store=True,
        help="The folder in the Documents app where this document is stored.",
    )

    @api.depends('ir_attachment_id')
    def _compute_document_folder_id(self):
        """Read the current folder from the linked documents.document."""
        attachment_ids = self.filtered('ir_attachment_id').mapped('ir_attachment_id').ids
        if attachment_ids:
            docs = self.env['documents.document'].sudo().search([
                ('attachment_id', 'in', attachment_ids),
            ])
            doc_by_attachment = {doc.attachment_id.id: doc for doc in docs}
        else:
            doc_by_attachment = {}

        for record in self:
            doc = doc_by_attachment.get(record.ir_attachment_id.id) if record.ir_attachment_id else None
            record.document_folder_id = doc.folder_id if doc else False

    def _inverse_document_folder_id(self):
        """Write the selected folder back to the linked documents.document."""
        records_with_folder = self.filtered(
            lambda r: r.document_folder_id and r.ir_attachment_id
        )
        if not records_with_folder:
            return

        attachment_ids = records_with_folder.mapped('ir_attachment_id').ids
        docs = self.env['documents.document'].sudo().search([
            ('attachment_id', 'in', attachment_ids),
        ])
        doc_by_attachment = {doc.attachment_id.id: doc for doc in docs}

        folder_to_docs = {}
        for record in records_with_folder:
            doc = doc_by_attachment.get(record.ir_attachment_id.id)
            if doc:
                folder_id = record.document_folder_id.id
                folder_to_docs.setdefault(folder_id, self.env['documents.document'])
                folder_to_docs[folder_id] |= doc

        for folder_id, doc_records in folder_to_docs.items():
            doc_records.write({'folder_id': folder_id})
