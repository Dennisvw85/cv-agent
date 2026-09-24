param name string
param location string

@description('Wie er mag inloggen, in het formaat van het GitHub OIDC-token')
param subject string

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
}

resource github 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: identity
  name: 'github-actions'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: subject
    audiences: ['api://AzureADTokenExchange']
  }
}

output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId
