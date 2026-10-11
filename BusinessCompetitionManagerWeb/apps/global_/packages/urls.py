from django.urls import path

from apps.global_.packages import views

urlpatterns = [
    path('competitions/<int:cid>/package', views.PackageUploadView.as_view()),
    path('competitions/<int:cid>/packages', views.PackageListView.as_view()),
    path('competitions/<int:cid>/contract-types', views.ContractTypeListView.as_view()),
    path('plugins', views.PluginRegistryView.as_view()),
]
