"""Administration Django — core_scolarite (UE, types de problème, règles)."""

from django.contrib import admin

from .models import (
    AttachmentConfig,
    AuditLog,
    ConditionalRule,
    Course,
    CourseAssignment,
    DecisionRule,
    FormField,
    ProblemType,
    ReminderPolicy,
    Service,
    ServiceAssignment,
    SlaPolicy,
    TechnicalEvent,
)


class AttachmentConfigInline(admin.TabularInline):
    """Éditer les règles de pièces jointes directement depuis le type de problème."""

    model = AttachmentConfig
    extra = 1
    fields = ("label", "is_required")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "department", "primary_instructor")
    list_filter = ("department__faculty", "department")
    search_fields = ("code", "name")
    autocomplete_fields = ("department", "primary_instructor")
    ordering = ("code",)
    readonly_fields = ("id",)


@admin.register(ProblemType)
class ProblemTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "requires_course", "attachment_count")
    list_filter = ("requires_course",)
    search_fields = ("name",)
    inlines = (AttachmentConfigInline,)
    ordering = ("name",)

    @admin.display(description="Pièces configurées")
    def attachment_count(self, obj):
        return obj.required_attachments.count()


@admin.register(AttachmentConfig)
class AttachmentConfigAdmin(admin.ModelAdmin):
    list_display = ("label", "problem_type", "is_required")
    list_filter = ("is_required", "problem_type")
    search_fields = ("label", "problem_type__name")
    autocomplete_fields = ("problem_type",)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "contact_email", "is_active", "member_count")
    list_filter = ("is_active", "university")
    search_fields = ("name", "contact_email")
    ordering = ("university__name", "name")
    readonly_fields = ("id", "created_at")

    @admin.display(description="Membres")
    def member_count(self, obj):
        return obj.assignments.filter(is_active=True).count()


@admin.register(ServiceAssignment)
class ServiceAssignmentAdmin(admin.ModelAdmin):
    list_display = ("service", "user", "role", "is_active")
    list_filter = ("role", "is_active", "service")
    search_fields = ("service__name", "user__username", "user__last_name")
    ordering = ("service__name", "user__last_name")


@admin.register(DecisionRule)
class DecisionRuleAdmin(admin.ModelAdmin):
    list_display = ("problem_type", "action", "scope", "is_active")
    list_filter = ("action", "scope", "is_active")
    search_fields = ("problem_type__name",)
    ordering = ("problem_type__name", "action")


@admin.register(SlaPolicy)
class SlaPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "problem_type", "max_days",
                    "blocked_after_days", "is_active")
    list_filter = ("is_active", "university")
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(ReminderPolicy)
class ReminderPolicyAdmin(admin.ModelAdmin):
    list_display = ("name", "delay_days", "target_role", "is_active")
    list_filter = ("target_role", "is_active")
    search_fields = ("name", "title")
    ordering = ("name",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Journal immuable : lecture seule dans l'admin Django."""

    list_display = ("created_at", "actor", "action", "model_label", "object_repr")
    list_filter = ("action", "model_label")
    search_fields = ("object_repr", "object_pk", "actor__username")
    ordering = ("-created_at",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TechnicalEvent)
class TechnicalEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "level", "source", "logger", "is_resolved", "short_message")
    list_filter = ("level", "source", "is_resolved")
    search_fields = ("message", "logger")
    ordering = ("-created_at",)
    readonly_fields = ("id", "created_at")

    @admin.display(description="Message")
    def short_message(self, obj):
        return obj.message[:80]


@admin.register(FormField)
class FormFieldAdmin(admin.ModelAdmin):
    list_display = ("label", "key", "problem_type", "field_type", "position", "is_active")
    list_filter = ("field_type", "is_active")
    search_fields = ("label", "key", "problem_type__name")
    ordering = ("problem_type__name", "position")


@admin.register(ConditionalRule)
class ConditionalRuleAdmin(admin.ModelAdmin):
    list_display = ("field", "depends_on", "operator", "value", "action")
    list_filter = ("operator", "action")
    search_fields = ("field__key", "depends_on__key", "field__problem_type__name")
    ordering = ("field__problem_type__name", "field__position")


@admin.register(CourseAssignment)
class CourseAssignmentAdmin(admin.ModelAdmin):
    list_display = ("course", "teacher", "academic_year", "department", "is_active")
    list_filter = ("is_active", "academic_year", "department")
    search_fields = ("course__code", "course__name", "teacher__user__last_name")
    ordering = ("-academic_year__code", "course__code")
