// Eenmalige bootstrap voor GitHub Actions: een managed identity die via OIDC mag inloggen
// om de evaluatie (evals/evaluate.py) te draaien. Staat bewust los van main.bicep, zodat
// `azd down` deze CI/CD-identiteit niet weggooit.
//
// Draait op resource group-scope in rg-cicd (bestaat al, gedeeld met andere projecten),
// en wijst daarna een rol toe op het Foundry-account in een andere resource group (rg-dev).
//
// Uitrollen (eenmalig, lokaal):
//   az deployment group create -g rg-cicd -f infra/bootstrap/cicd.bicep \
//     -p githubOwner=<owner> githubRepo=<repo> githubOwnerId=<id> githubRepoId=<id> \
//        foundryAccountName=<naam> foundryResourceGroup=<rg>
// De GitHub-ID's haal je op met: gh api repos/<owner>/<repo> --jq '.owner.id, .id'
targetScope = 'resourceGroup'

param location string = resourceGroup().location

@description('GitHub-gebruiker of -organisatie die de repo bezit')
param githubOwner string

@description('Naam van de GitHub-repo')
param githubRepo string

@description('Numerieke ID van de owner; nieuwe repo\'s zetten die in het OIDC-subject')
param githubOwnerId string = ''

@description('Numerieke ID van de repo; nieuwe repo\'s zetten die in het OIDC-subject')
param githubRepoId string = ''

@description('GitHub-environment waaruit gedeployd mag worden')
param githubEnvironment string = 'eval'

@description('Naam van het Foundry-account (Cognitive Services-account) waar de evaluatie tegenaan praat')
param foundryAccountName string

@description('Resource group van het Foundry-account, kan afwijken van deze resource group')
param foundryResourceGroup string

var ownerPart = empty(githubOwnerId) ? githubOwner : '${githubOwner}@${githubOwnerId}'
var repoPart = empty(githubRepoId) ? githubRepo : '${githubRepo}@${githubRepoId}'

// Foundry User: agents en modellen aanroepen via de AI Project-endpoint.
// Cognitive Services User: de azure-ai-evaluation-evaluators (IntentResolution, TaskAdherence,
// Groundedness) praten rechtstreeks tegen het cognitiveservices.azure.com-endpoint, niet via het
// project. De bestaande identities op dit account (de api- en api-v2-containerapps) hebben allebei
// de rollen, dus die combinatie is hier het geverifieerde minimum, geen Contributor.
var foundryUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

module identity 'identity.bicep' = {
  name: 'id-gh-${githubRepo}-${githubEnvironment}'
  params: {
    name: 'id-gh-${githubRepo}'
    location: location
    subject: 'repo:${ownerPart}/${repoPart}:environment:${githubEnvironment}'
  }
}

module foundryRole 'foundry-role.bicep' = {
  name: 'foundry-role-${githubRepo}'
  scope: resourceGroup(foundryResourceGroup)
  params: {
    principalId: identity.outputs.principalId
    foundryAccountName: foundryAccountName
    roleIds: [foundryUserRoleId, cognitiveServicesUserRoleId]
  }
}

output AZURE_CLIENT_ID string = identity.outputs.clientId
