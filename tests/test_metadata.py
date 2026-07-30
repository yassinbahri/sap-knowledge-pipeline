from __future__ import annotations

from sap_knowledge.sources.odata import ODataVersion, parse_metadata

V4_METADATA = b"""\
<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">
  <edmx:DataServices>
    <Schema Namespace="Demo" xmlns="http://docs.oasis-open.org/odata/ns/edm">
      <EntityType Name="Notification">
        <Key><PropertyRef Name="ID" /></Key>
        <Property Name="ID" Type="Edm.String" Nullable="false" MaxLength="12" />
        <Property Name="Text" Type="Edm.String" />
        <NavigationProperty Name="Equipment" Type="Demo.Equipment" />
      </EntityType>
      <EntityContainer Name="Container">
        <EntitySet Name="Notifications" EntityType="Demo.Notification" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


V2_METADATA = b"""\
<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema Namespace="Northwind" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">
      <EntityType Name="Product">
        <Key><PropertyRef Name="ProductID" /></Key>
        <Property Name="ProductID" Type="Edm.Int32" Nullable="false" />
        <Property Name="ProductName" Type="Edm.String" Nullable="false" />
      </EntityType>
      <EntityContainer Name="Entities">
        <EntitySet Name="Products" EntityType="Northwind.Product" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


def test_parse_v4_metadata() -> None:
    metadata = parse_metadata(V4_METADATA)
    notifications = metadata.entity_set("Notifications")

    assert metadata.version is ODataVersion.V4
    assert notifications.keys == ("ID",)
    assert notifications.property("ID").nullable is False
    assert notifications.property("ID").max_length == "12"
    assert notifications.navigation_properties == ("Equipment",)


def test_parse_v2_metadata() -> None:
    metadata = parse_metadata(V2_METADATA)

    assert metadata.version is ODataVersion.V2
    assert metadata.entity_set("Products").keys == ("ProductID",)
