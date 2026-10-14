"""Administration Django — tickets (workflow, statuts, pièces jointes)."""

from django.contrib import admin

from .models import Ticket, TicketAttachment, TicketStatusHistory


class TicketStatusHistoryInline(admin.TabularInline):
    model = TicketStatusHistory
    extra = 0
    can_delete = False
    fields = ("from_status", "to_status", "actor", "actor_role", "note", "created_at")
    readonly_fields = fields
    ordering = ("created_at",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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
    inlines = (TicketAttachmentInline, TicketStatusHistoryInline)
    fieldsets = (
        (None, {"fields": ("id", "status", "problem_type", "description")}),
        ("Acteurs", {"fields": ("student", "teacher", "course")}),
        ("Décision", {"fields": ("rejection_reason", "received_at", "resolved_at")}),
        ("Traçabilité", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Référence")
    def short_id(self, obj):
        return obj.short_id


@admin.register(TicketStatusHistory)
class TicketStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("ticket", "from_status", "to_status", "actor", "actor_role", "created_at")
    list_filter = ("to_status", "actor_role")
    search_fields = ("ticket__student__registration_number", "note")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = [f.name for f in TicketStatusHistory._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Journal immuable : lecture seule, y compris pour le super-admin
        # (les entrées ne sont créées que par les services métier).
        return False

    def has_delete_permission(self, request, obj=None):
        return False
