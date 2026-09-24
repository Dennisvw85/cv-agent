// De bestaande CV-site: naar Standard, met wachtwoord, en de Function App als /api-backend.
// Wordt uitgerold naar de resource group van de site, apart van azd (zie README: waarom).
param staticSiteName string
param location string = resourceGroup().location
param repositoryUrl string
param functionAppId string
param functionAppLocation string

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
    stagingEnvironmentPolicy: 'Disabled'
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
    backendResourceId: functionAppId
    region: functionAppLocation
  }
}

output defaultHostname string = site.properties.defaultHostname
