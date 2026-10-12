from django.contrib import admin

from .models import (
    Fuel, Infrastructure, MapEdge, MapNode, MapNodeType, Material, Part,
    PartMaterial, PartTechRequirement, PathType, Product, ProductPart,
    ProductTechRequirement, ProductionLine, TechNode, TechPrerequisite,
    Vehicle, VehiclePathType, Warehouse,
)

admin.site.register([
    Fuel, Warehouse, Vehicle, VehiclePathType,
    MapNodeType, PathType, MapNode, MapEdge,
    Material, Product, ProductPart, ProductTechRequirement,
    Part, PartMaterial, PartTechRequirement,
    Infrastructure, TechNode, TechPrerequisite, ProductionLine,
])
