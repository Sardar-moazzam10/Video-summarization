describe('DPS Sanity Check', () => {
    it('loads homepage successfully', () => {
      cy.visit('/')
      cy.contains(/login|signup/i)
    })
  })