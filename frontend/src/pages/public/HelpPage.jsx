import React from 'react'
import { useRouter } from '../../router/RouterContext'
import './Pages.css'

export default function HelpPage() {
  const { navigate } = useRouter()

  return (
    <div className="page-container help-page">
      <div className="card">
        <span className="badge badge-accent">VOTER ASSISTANCE</span>
        <h2 className="card-title">Frequently Asked Questions & Help</h2>
        <p>Step-by-step guidance for student voters participating in college e-voting.</p>
      </div>

      <div className="section-block">
        <div className="card">
          <h4>Q: How do I register to vote?</h4>
          <p>
            Navigate to the <button className="link-button" onClick={() => navigate('/register')}>Registration page</button>.
            Enter your official college USN. A 6-digit verification code will be sent to your institutional email.
            Once verified, choose your password. You can then sign in to complete wallet binding and biometric face enrollment.
          </p>
        </div>

        <div className="card">
          <h4>Q: What do I need before voting?</h4>
          <p>
            You need three items verified on your student dashboard:
            <br />1. Verified college login session.
            <br />2. A desktop browser with the MetaMask wallet extension installed (Ethereum Ganache / Sepolia network).
            <br />3. A working webcam with permission enabled for active face liveness.
          </p>
        </div>

        <div className="card">
          <h4>Q: Can anyone see who I voted for?</h4>
          <p>
            <strong>No.</strong> Your ballot selection is encrypted and processed via an asynchronous relayer that shuffles votes.
            The blockchain only records cryptographic pseudonyms. Furthermore, the keys needed to derive those pseudonyms are permanently destroyed upon election finalization.
          </p>
        </div>

        <div className="card">
          <h4>Q: What if I made a mistake or was forced to vote for someone?</h4>
          <p>
            Under collegiate controlled revoting rules, you may revote up to <strong>3 times</strong> (with a 120-second cooldown).
            Only your latest valid vote is tallied. You can also cast a Null Ballot to retract your vote completely.
          </p>
        </div>

        <div className="card">
          <h4>Q: What happens if my camera or MetaMask fails during voting?</h4>
          <p>
            Your ballot is only cast once you reach the final confirmation and click "Confirm & Cast Ballot".
            If a factor check fails, you can re-run camera or wallet verification at any time before election close.
            If you need technical support, <button className="link-button" onClick={() => navigate('/report-problem')}>Report a Problem</button>.
          </p>
        </div>
      </div>
    </div>
  )
}
