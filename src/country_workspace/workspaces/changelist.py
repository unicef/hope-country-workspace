from django.contrib.admin.utils import quote
from django.contrib.admin.views.main import ChangeList as DjangoChangeList
from django.urls import reverse


class WorkspaceChangeList(DjangoChangeList):

    def url_for_result(self, result):
        pk = getattr(result, self.pk_attname)
        return reverse(
            "%s:%s_%s_change"
            % (
                self.model_admin.admin_site.namespace,
                self.opts.app_label,
                self.opts.model_name,
            ),
            args=(quote(pk),),
            current_app=self.model_admin.admin_site.name,
        )
