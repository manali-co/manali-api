// manali apps backend: one storage account (tables + Functions host), one Flex Consumption
// Function App, wired to the Application Insights that already exists in the subscription
// so site, API and email traffic land in one place.
targetScope = 'resourceGroup'

@description('Short environment name, e.g. dev or prod')
param env string = 'dev'
param location string = resourceGroup().location
@description('Resource id of the existing Application Insights component to report to')
param appInsightsId string
@secure()
param apiKey string
@secure()
param tokenSecret string
@secure()
param resendApiKey string = ''
param siteUrl string = 'https://manali-co.github.io'
param mailFrom string = 'manali apps <hello@manali.app>'

var name = 'manali-${env}'
var storageName = replace('st${name}${uniqueString(resourceGroup().id)}', '-', '')

resource appi 'Microsoft.Insights/components@2020-02-02' existing = {
  name: last(split(appInsightsId, '/'))
  scope: resourceGroup(split(appInsightsId, '/')[2], split(appInsightsId, '/')[4])
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: take(storageName, 24)
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { minimumTlsVersion: 'TLS1_2', allowBlobPublicAccess: false, supportsHttpsTrafficOnly: true }
}

resource deployContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  name: '${storage.name}/default/deployments'
}

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${name}-plan'
  location: location
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2023-12-01' = {
  name: '${name}-api'
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: { storage: { type: 'blobContainer', value: '${storage.properties.primaryEndpoints.blob}deployments', authentication: { type: 'SystemAssignedIdentity' } } }
      runtime: { name: 'python', version: '3.12' }
      scaleAndConcurrency: { maximumInstanceCount: 40, instanceMemoryMB: 2048 }
    }
    siteConfig: {
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
        { name: 'MANALI_TABLES_ENDPOINT', value: storage.properties.primaryEndpoints.table }
        { name: 'MANALI_API_KEY', value: apiKey }
        { name: 'MANALI_TOKEN_SECRET', value: tokenSecret }
        { name: 'RESEND_API_KEY', value: resendApiKey }
        { name: 'MANALI_SITE_URL', value: siteUrl }
        { name: 'MANALI_MAIL_FROM', value: mailFrom }
      ]
    }
  }
}

// The function's identity reads/writes the tables and its own deployment blobs.
var roles = {
  tableContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  blobOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  queueContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
}
resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in items(roles): {
  name: guid(storage.id, func.id, role.value)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.value)
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

output apiUrl string = 'https://${func.properties.defaultHostName}/api'
output functionAppName string = func.name
output storageAccount string = storage.name
