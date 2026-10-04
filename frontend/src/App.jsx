import './App.css'
import Auth from './Auth'
import Registration from './Registration'
import Wallet from './Wallet'
import Face from './Face'

function App() {
  return (
    <div className="app-container">
      <h1>Vote Without Doubt</h1>
      <p>AI & Blockchain-Based Secure E-Voting System</p>
      <div className="sections">
        <Auth />
        <Registration />
        <Wallet />
        <Face />
      </div>
    </div>
  )
}

export default App

