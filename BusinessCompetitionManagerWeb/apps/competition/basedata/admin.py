from django.contrib import admin

from .models import (
    Fuel, Infrastructure, MapRegion, Material, Part, Product,
    ProductionLine, TechNode, Vehicle, Warehouse,
)

admin.site.register([Fuel, Warehouse, Vehicle, MapRegion, Material,
                     Product, Part, Infrastructure, TechNode, ProductionLine])
