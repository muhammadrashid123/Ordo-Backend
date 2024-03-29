from django.db import migrations


def move_bone_graft_to_grafting(apps, schema_editor):
    ProcedureCategory = apps.get_model('orders', 'ProcedureCategoryLink')
    ProcedureCode = apps.get_model('orders', 'ProcedureCode')

    category_graft = ProcedureCategory.objects.filter(summary_slug='Bone Graft').first()
    category_grafting = ProcedureCategory.objects.filter(summary_slug='Bone Grafting').first()
    modify_proc_codes = ProcedureCode.objects.filter(summary_category=category_graft)
    if category_graft and category_grafting:
        # Update summary_category with Bone Graft to Bone Grafting
        for proc_code in modify_proc_codes:
            proc_code.summary_category = category_grafting
            proc_code.save(update_fields=['summary_category'])

        # Combine linked_slugs
        slugs_category_graft = category_graft.linked_slugs
        slugs_category_grafting = category_grafting.linked_slugs
        merged_slugs = []
        if slugs_category_graft:
            merged_slugs = slugs_category_graft
        if slugs_category_grafting:
            merged_slugs = merged_slugs + slugs_category_grafting

        merged_slugs = list(dict.fromkeys(merged_slugs))
        category_grafting.linked_slugs = merged_slugs
        category_grafting.save()

        # Remove Bone Graft
        category_graft.delete()




class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0060_procedurecode_search_vector_and_more'),
    ]

    operations = [
        migrations.RunPython(move_bone_graft_to_grafting),
    ]
