describe('Setup event for checkin', function() {
  const { admin } = require('../fixtures/user.js');
  const project = require('../fixtures/project.json');
  const events = require('../fixtures/events.json');
  const participants = require('../fixtures/participants.json');

  it('Setup event for checkin', function() {
    cy.server();
    cy.route('POST', '**/participants/checkin?*').as('checkin');
    cy.route('**/participants/json').as('participant-list');

    cy.relogin('/testcypressproject');
    cy.get('[data-cy-project="' + project.title + '"]')
      .first()
      .click();
    cy.location('pathname').should('contain', project.url);
    cy.get('a[data-cy-navbar="settings"]').click();
    cy.location('pathname').should('contain', 'settings');
    cy.get('a[data-cy="checkin"').click();
    cy.location('pathname').should('contain', '/admin');

    cy.fixture('events').then(events => {
      events.forEach(function(event) {
        cy.get('a[data-cy="new-event"]').click();
        cy.get('#title').type(event.title);
        cy.get('#badge_template').type(event.badge_template);
        cy.get('button')
          .contains('Add event')
          .click();
      });
    });

    cy.fixture('participants').then(participants => {
      participants.forEach(function(participant) {
        cy.get('a[data-cy="add-participant"]').click();
        cy.get('#fullname').type(participant.fullname);
        cy.get('#email').type(participant.email);
        cy.get('#phone').type(participant.phone);
        cy.get('#company').type(participant.company);
        cy.get('#twitter').type(participant.twitter);
        cy.get('#field-events')
          .find('label')
          .contains(participant.event)
          .click();
        cy.get('button')
          .contains('Add participant')
          .click();
      });
    });

    cy.get('a[data-cy="' + events[0].title + '"]').click();
    cy.get('td[data-th="Name"]').contains(participants[0].fullname);
    cy.get('td[data-th="Name"]').contains(participants[1].fullname);
    cy.get('a[data-cy="back-to-setup"]').click();

    cy.get('a[data-cy="' + events[1].title + '"]').click();
    cy.get('td[data-th="Name"]').contains(participants[2].fullname);

    // Test failing
    // cy.get('a[data-cy="edit-attendee-details"]')
    //   .invoke('removeAttr', 'target')
    //   .click();
    // cy.url().should('contain', 'edit');
    // cy.get('#email')
    //   .clear()
    //   .type(participants[1].email);
    // cy.get('button')
    //   .contains('Save changes')
    //   .click();

    cy.get('button[data-cy="checkin"]').click();
    cy.wait('@checkin', { timeout: 15000 });

    cy.wait('@participant-list', { timeout: 15000 });
    cy.wait('@participant-list', { timeout: 15000 });
    cy.wait('@participant-list', { timeout: 15000 }).then(xhr => {
      cy.get('button[data-cy="cancel-checkin"]').should('exist');
    });
  });
});
