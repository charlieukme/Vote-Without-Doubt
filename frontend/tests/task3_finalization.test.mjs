import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const resultsPagePath = path.join(HERE, '..', 'src', 'pages', 'admin', 'AdminResultsPage.jsx')
const approvalsPagePath = path.join(HERE, '..', 'src', 'pages', 'admin', 'AdminApprovalsPage.jsx')

const resultsSrc = fs.readFileSync(resultsPagePath, 'utf8')
const approvalsSrc = fs.readFileSync(approvalsPagePath, 'utf8')

test('AdminResultsPage restricts finalization request to commissioned Officers', () => {
  assert.match(resultsSrc, /isOfficer\s*&&/, 'Finalization request action must be guarded by isOfficer')
  assert.match(resultsSrc, /adminAuth\?\.role === 'OFFICER'/, 'Officer role must be checked from adminAuth')
})

test('AdminResultsPage exposes Request Finalization during PROVISIONAL_UNFINALIZED state', () => {
  assert.match(resultsSrc, /resultState === 'PROVISIONAL_UNFINALIZED'/, 'Must inspect PROVISIONAL_UNFINALIZED state')
  assert.match(resultsSrc, /Request Finalization/, 'Must render Request Finalization button')
})

test('AdminResultsPage displays pending approval banner and prevents duplicate requests', () => {
  assert.match(resultsSrc, /activeFinalizeApproval/, 'Must track activeFinalizeApproval state')
  assert.match(resultsSrc, /a\.action_type === 'FINALIZE_ELECTION' &&\s*a\.status === 'PENDING'/, 'Must filter for pending FINALIZE_ELECTION')
  assert.match(resultsSrc, /\/admin\/approvals/, 'Must link to approvals queue')
  assert.match(resultsSrc, /Four-Eyes Notice/, 'Must alert requester that self-approval is forbidden')
})

test('AdminResultsPage collects meaningful justification with irreversible warning modal', () => {
  assert.match(resultsSrc, /finalizeReason\.trim\(\)\.length < 10/, 'Must validate minimum 10 characters for justification')
  assert.match(resultsSrc, /IRREVERSIBLE CRYPTOGRAPHIC SETTLEMENT/, 'Must display irreversible settlement warning')
  assert.match(resultsSrc, /RFC 6962 Merkle tree/, 'Must warn about Merkle tree sealing')
  assert.match(resultsSrc, /pseudonym key material/, 'Must warn about pseudonym key destruction')
})

test('AdminApprovalsPage formats FINALIZE_ELECTION with distinct styling', () => {
  assert.match(approvalsSrc, /FINALIZE_ELECTION/, 'Approvals queue must identify FINALIZE_ELECTION')
  assert.match(approvalsSrc, /Approve & Finalize/, 'Must customize approval button label for finalization')
})

test('AdminApprovalsPage distinguishes precondition failures from manual officer rejections', () => {
  assert.match(approvalsSrc, /Finalization blocked:/, 'Must inspect persisted rejection reason for finalization blocker')
  assert.match(approvalsSrc, /Precondition Check Failed:/, 'Must label execution failures distinct from officer rejections')
  assert.match(approvalsSrc, /Officer Rejection Reason:/, 'Must label manual officer rejections cleanly')
})

test('AdminApprovalsPage strictly prevents self-approval in the UI', () => {
  assert.match(approvalsSrc, /Self-Approval Blocked/, 'Must indicate self-approval block in the UI')
  assert.match(approvalsSrc, /currentAdminId === requesterId/, 'Must guard approve handler against self-approval')
})

