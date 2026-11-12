/**
 * Error boundary - Phase 1 frontend foundation.
 *
 * A render-time exception in any component previously unmounted the whole app
 * and left a blank page. This boundary catches it and shows a recoverable
 * neo-brutalist panel: thick black border, hard shadow, no blur, no gradient,
 * `role="alert"` so assistive technology announces it, and a real focusable
 * button rather than a click handler on a non-interactive element.
 *
 * Accessibility: the retry control is a native `<button>`, the message is a live
 * region, and focus is not stolen from the user mid-interaction.
 */

import { Component } from 'react'

export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
    this.handleReset = this.handleReset.bind(this)
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Keep the detail in the console for developers; never render a stack trace
    // or internal message to the voter.
    console.error('Unhandled UI error:', error, info?.componentStack)
    this.props.onError?.(error, info)
  }

  handleReset() {
    this.setState({ error: null })
    this.props.onReset?.()
  }

  render() {
    const { error } = this.state
    if (!error) {
      return this.props.children
    }

    if (this.props.fallback) {
      return typeof this.props.fallback === 'function'
        ? this.props.fallback(error, this.handleReset)
        : this.props.fallback
    }

    return (
      <div className="error-boundary" role="alert" aria-live="assertive">
        <div className="error-boundary__panel">
          <h1 className="error-boundary__title">Something went wrong</h1>
          <p className="error-boundary__message">
            The interface hit an unexpected error. Your session has not been
            changed. You can retry safely.
          </p>
          <button
            type="button"
            className="error-boundary__retry"
            onClick={this.handleReset}
          >
            Try again
          </button>
        </div>
      </div>
    )
  }
}

export default ErrorBoundary