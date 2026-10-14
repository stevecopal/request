"""Administration Django — core_scolarite (UE, types de problème, règles)."""

from django.contrib import admin

from .models import AttachmentConfig, Course, ProblemType


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
