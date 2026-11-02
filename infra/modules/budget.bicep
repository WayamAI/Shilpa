// Monthly cost budget on the resource group with alerts at 50/80/100% of actual spend.
// Budgets alert; they do not stop spend (admission control in the app does that, blueprint section 21).
param name string
@minValue(1)
param amount int
@minLength(1)
param contactEmails array
@description('Must be the first day of a month (yyyy-MM-01).')
param startDate string = utcNow('yyyy-MM-01')
param thresholds array = [50, 80, 100]

var notifications = toObject(thresholds, t => 'Actual_GreaterThan_${t}_Percent', t => {
  enabled: true
  operator: 'GreaterThan'
  threshold: t
  thresholdType: 'Actual'
  contactEmails: contactEmails
})

resource budget 'Microsoft.Consumption/budgets@2026-06-01' = {
  name: name
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: { startDate: startDate }
    notifications: notifications
  }
}
