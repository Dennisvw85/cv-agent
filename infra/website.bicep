// De bestaande CV-site: naar Standard, met wachtwoord, en de Container App als /api-backend.
// Wordt uitgerold naar de resource group van de site, apart van azd (zie README: waarom).
param staticSiteName string
param location string = resourceGroup().location
param repositoryUrl string
param apiResourceId string
param apiLocation string

@description('Container App voor de v2-omgeving; leeg = geen v2-koppeling')
param apiV2ResourceId string = ''

@secure()
@description('Wachtwoord voor bezoekers: min. 8 tekens met hoofdletter, kleine letter, cijfer en symbool')
param sitePassword string

resource site 'Microsoft.Web/staticSites@2024-04-01' = {
  name: staticSiteName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    repositoryUrl: repositoryUrl
    branch: 'main'
    provider: 'GitHub'
    // Enabled: naast productie (main) kan een aparte v2-omgeving draaien.
    stagingEnvironmentPolicy: 'Enabled'
    allowConfigFileUpdates: true
  }
}

resource password 'Microsoft.Web/staticSites/basicAuth@2024-04-01' = {
  parent: site
  name: 'default'
  properties: {
    password: sitePassword
    secretUrl: ''
    applicableEnvironmentsMode: 'AllEnvironments'
  }
}

resource backend 'Microsoft.Web/staticSites/linkedBackends@2024-04-01' = {
  parent: site
  name: 'cv-agent-api'
  properties: {
    backendResourceId: apiResourceId
    region: apiLocation
  }
}

resource v2Build 'Microsoft.Web/staticSites/builds@2024-04-01' existing = if (!empty(apiV2ResourceId)) {
  parent: site
  name: 'v2'
}

resource v2Backend 'Microsoft.Web/staticSites/builds/linkedBackends@2024-04-01' = if (!empty(apiV2ResourceId)) {
  parent: v2Build
  name: 'cv-agent-api-v2'
  properties: {
    backendResourceId: apiV2ResourceId
    region: apiLocation
  }
}

output defaultHostname string = site.properties.defaultHostname
