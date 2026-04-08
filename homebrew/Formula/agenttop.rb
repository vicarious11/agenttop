class Agenttop < Formula
  include Language::Python::Virtualenv

  desc "htop for AI coding agents — monitor Claude Code, Cursor, Kiro, Copilot and more"
  homepage "https://github.com/vicarious11/agenttop"
  url "https://github.com/vicarious11/agenttop/archive/refs/tags/v0.1.0.tar.gz"
  # SHA256 generated after release: shasum -a 256 agenttop-<version>.tar.gz
  # CI workflow (.github/workflows/release.yml) auto-updates this on tag push
  sha256 "PLACEHOLDER_SHA256"
  license "Apache-2.0"
  head "https://github.com/vicarious11/agenttop.git", branch: "main"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      To get started:
        agenttop              # TUI dashboard
        agenttop web          # Web dashboard at localhost:8420
        agenttop init         # Configure LLM for AI analysis
    EOS
  end

  test do
    assert_match "agenttop", shell_output("#{bin}/agenttop --version")
  end
end
