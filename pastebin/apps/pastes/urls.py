from django.urls import path

from . import views

urlpatterns = [
    path("pastes", views.create_paste),
    path("pastes/<str:pid>", views.paste_detail),
    path("me/pastes", views.my_pastes),
]
