"""Administration Django — tickets (workflow, statuts, pièces jointes)."""

from django.contrib import admin

from .models import Ticket, TicketAttachment


class TicketAttachmentInline(admin.TabularInline):
    model = TicketAttachment
    extra = 0
    fields = ("config", "file")
    readonly_fields = ("id",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("short_id", "problem_type", "student", "teacher", "status", "created_at")
    list_filter = ("status", "problem_type", "teacher__department__faculty")
    search_fields = (
        "student__registration_number",
        "student__user__last_name",
        "description",
    )
    autocomplete_fields = ("student", "teacher", "course", "problem_type")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = (TicketAttachmentInline,)
    fieldsets = (
        (None, {"fields": ("id", "status", "problem_type", "description")}),
        ("Acteurs", {"fields": ("student", "teacher", "course")}),
        ("Décision", {"fields": ("rejection_reason", "received_at", "resolved_at")}),
        ("Traçabilité", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Référence")
    def short_id(self, obj):
        return obj.short_id
