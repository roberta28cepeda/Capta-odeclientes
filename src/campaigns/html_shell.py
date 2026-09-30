"""Casca de HTML compartilhada por todas as teses da campanha — mesmo
design usado hoje no Apps Script (cabeçalho degradê teal com logo da
Leactis, checklist, botão de CTA, rodapé com endereço/CNPJ real,
cancelamento de inscrição). Cada tese só define o conteúdo variável
(tag, título, parágrafos, checklist, CTA); o resto é sempre igual, o que
evita duplicar ~8KB de HTML/logo em cada template salvo no banco.
"""

from __future__ import annotations

# Logo da Leactis em base64 — mesmo arquivo usado nos e-mails atuais do Apps Script.
_LOGO_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAMgAAADGCAMAAACgjD/cAAAB/lBMVEX29/ctl6okeJIbZ4Yyp7QnhZs7x8tE09QYWns4usMD1NMoi6E2s7wcdI9FyM3N5+ywytUjaog71dOI2tux0trU9PWx5ugZXIEiXHl2ycxPp7CPx85RtLhy1tRJh5iu2uJMmKVHusVvp7NttbuLucQYYnxGeI4NzM4pZHscg5dsmaiovs1wusLr7fSS5OTH3OQukp2HtL2N4dvG1dtKlJyEqraz8fA4rMBiiZqR3OE0w75SjqInfaITlaoTpLMah6AhXIF54+IVsL0TusRBbIFGwbpR4Nh43+Fs4d2Z8PK44N8ScH8Z4sdCqsBB1eBd5uFll55pxb6LqsDCy9MAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADQE8xVAAAAgHRSTlP///////////////////////////////////////////////////////////////////////////////////////////////////////////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAzgTMsAABHfSURBVHja7Z0He+JIEoZRliwkIZER2YDB4zjjSTtzG273dm/38t3//y/XSVJ3dQuwBzD4cT22hyGIflX1dbc6lCqVvVurWXkZNqi/DI6643x4CRyR4ziDlxBcA9txwpvT52iFoZMk4cm7pNm1QxRbycnr/XMYYhAnbJ24Q0KbgiQnrveBbROXJCeu91aYgzjOKbukGxISh7hkcMIOsW3mEYJysnpHVS8lYSAnq/f6d2EGgjSSJM7bE+1kYX0UIJgkOk2lezYfWiS4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"
)

REMETENTE_NOME = "Paulo Eduardo Leão"
REMETENTE_EMPRESA = "Leactis Consultoria"
REMETENTE_TELEFONE = "(21) 98695-6773"
RODAPE_CNPJ = "63.586.147/0001-25"
RODAPE_ENDERECO = "Av. Vice-Presidente José Alencar, 1515, Apt 601 Bloco 006, Jacarepaguá<br>Rio de Janeiro/RJ, CEP 22.775-033"
RODAPE_EMAIL = "contato@leactis.com.br"


def _checklist_html(itens: list[str]) -> str:
    linhas = []
    for i, item in enumerate(itens):
        padding_bottom = "16px" if i == len(itens) - 1 else "6px"
        padding_top = "16px" if i == 0 else "6px"
        linhas.append(
            f'<tr><td style="padding:{padding_top} 20px {padding_bottom} 20px; font-size:15.5px; line-height:24px; color:#0c1a1a;">'
            '<span style="display:inline-block; width:20px; height:20px; background-color:#136868; border-radius:50%; '
            'text-align:center; line-height:20px; color:#ffffff; font-size:12px; font-weight:bold;">&#10003;</span>'
            f"&nbsp;&nbsp;{item}</td></tr>"
        )
    return "\n".join(linhas)


def render_email_html(
    tag: str,
    headline: str,
    paragrafo1: str,
    paragrafo2: str,
    checklist: list[str],
    italico: str,
    cta_texto: str,
    cta_url: str,
    rodape_nota: str,
    pixel_html: str = "",
) -> str:
    """Monta o HTML completo do e-mail no design padrão da Leactis, com o
    conteúdo variável de cada tese/tipo de envio já substituído.
    """
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Leactis</title>
</head>
<body style="margin:0; padding:0; background-color:#e8ecec; font-family: 'Trebuchet MS', Verdana, Arial, sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#e8ecec; padding:40px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff; max-width:600px; width:100%; border-radius:14px; overflow:hidden; box-shadow:0 6px 24px rgba(12,74,74,0.14);">

        <tr><td>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#0c4a4a; background:linear-gradient(135deg,#0a3d3d 0%,#136868 55%,#189384 100%);">
            <tr><td align="center" style="padding:30px 0 14px 0;">
              <table role="presentation" cellpadding="0" cellspacing="0" style="background-color:#ffffff; border-radius:50%; width:96px; height:96px;">
                <tr><td align="center" valign="middle" style="width:96px; height:96px;">
                  <img src="data:image/png;base64,{_LOGO_BASE64}" alt="Leactis" width="66" style="display:block; width:66px; height:auto;">
                </td></tr>
              </table>
            </td></tr>
            <tr><td align="center" style="padding:0 40px 4px 40px;">
              <table role="presentation" cellpadding="0" cellspacing="0" style="background-color:rgba(255,255,255,0.15); border-radius:20px; border:1px solid rgba(255,255,255,0.4);">
                <tr><td style="padding:6px 16px;">
                  <p style="margin:0; color:#7ff5e3; font-size:11.5px; font-weight:bold; letter-spacing:1px; text-transform:uppercase;">{tag}</p>
                </td></tr>
              </table>
            </td></tr>
            <tr><td style="padding:14px 40px 32px 40px;" valign="middle">
              <p style="color:#ffffff; font-size:22px; line-height:31px; margin:0; font-weight:bold; text-align:center;">
                {headline}
              </p>
            </td></tr>
          </table>
        </td></tr>

        <tr><td style="padding: 38px 40px 8px 40px;">
          <p style="font-size:21px; color:#0c1a1a; margin:0 0 22px 0; font-weight:bold;">Olá,</p>

          <p style="font-size:16px; line-height:26px; color:#333333; margin:0 0 20px 0;">
            {paragrafo1}
          </p>

          <p style="font-size:16px; line-height:26px; color:#333333; margin:0 0 20px 0;">
            {paragrafo2}
          </p>

          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin:0 0 20px 0; background-color:#f2f9f8; border-radius:10px; border:1px solid #e2f0ee;">
{_checklist_html(checklist)}
          </table>

          <p style="font-size:14.5px; line-height:22px; color:#136868; font-style:italic; margin:0 0 30px 0;">
            {italico}
          </p>

          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin:0 0 10px 0;">
            <tr><td align="center">
              <table role="presentation" cellpadding="0" cellspacing="0">
                <tr><td align="center" style="background-color:#0c4a4a; border-radius:8px; box-shadow:0 4px 12px rgba(12,74,74,0.28);">
                  <a href="{cta_url}" target="_blank" style="display:inline-block; padding:17px 38px; font-size:15px; font-weight:bold; color:#ffffff; text-decoration:none; letter-spacing:0.6px;">
                    {cta_texto}
                  </a>
                </td></tr>
              </table>
            </td></tr>
          </table>
          <p style="text-align:center; font-size:12.5px; color:#888888; margin:0 0 4px 0;">Diagnóstico inicial gratuito, sem compromisso</p>
          <p style="text-align:center; font-size:12.5px; color:#888888; margin:0 0 28px 0;">Prefere e-mail? Basta responder esta mensagem que retornamos rapidamente.</p>

          <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-top:1px solid #e5e9e9; padding-top:20px;">
            <tr><td style="padding-top:20px; font-size:14px; line-height:21px; color:#333333;">
              Fico à disposição.<br><br>
              <strong>{REMETENTE_NOME}</strong><br>
              <span style="color:#666666;">{REMETENTE_EMPRESA}</span><br>
              <span style="color:#666666;">{REMETENTE_TELEFONE}</span>
            </td></tr>
          </table>
        </td></tr>

        <tr><td style="padding:24px 40px 0 40px;"><hr style="border:none; border-top:1px solid #e5e9e9; margin:0 0 26px 0;"></td></tr>

        <tr><td align="center" style="padding:0 32px 22px 32px;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="padding:0 5px;"><a href="#" style="display:inline-block; width:34px; height:34px; background-color:#0c4a4a; border-radius:50%; text-align:center; line-height:34px; color:#ffffff; text-decoration:none; font-size:14px; font-weight:bold;">f</a></td>
            <td style="padding:0 5px;"><a href="#" style="display:inline-block; width:34px; height:34px; background-color:#0c4a4a; border-radius:50%; text-align:center; line-height:34px; color:#ffffff; text-decoration:none; font-size:14px; font-weight:bold;">X</a></td>
            <td style="padding:0 5px;"><a href="#" style="display:inline-block; width:34px; height:34px; background-color:#0c4a4a; border-radius:50%; text-align:center; line-height:34px; color:#ffffff; text-decoration:none; font-size:14px;">&#9678;</a></td>
            <td style="padding:0 5px;"><a href="#" style="display:inline-block; width:34px; height:34px; background-color:#0c4a4a; border-radius:50%; text-align:center; line-height:34px; color:#ffffff; text-decoration:none; font-size:13px; font-weight:bold;">in</a></td>
          </tr></table>
        </td></tr>

        <tr><td align="center" style="padding:0 32px 4px 32px;"><p style="font-size:14px; color:#0c4a4a; margin:0; font-weight:bold; letter-spacing:0.6px;">LEACTIS</p></td></tr>
        <tr><td align="center" style="padding:0 32px 6px 32px;"><a href="mailto:{RODAPE_EMAIL}" style="color:#0c4a4a; font-size:13px; text-decoration:underline;">{RODAPE_EMAIL}</a></td></tr>
        <tr><td align="center" style="padding:8px 32px 4px 32px;">
          <p style="font-size:12.5px; color:#888888; margin:0; line-height:19px;">
            CNPJ {RODAPE_CNPJ}<br>
            {RODAPE_ENDERECO}
          </p>
        </td></tr>
        <tr><td align="center" style="padding:8px 32px 8px 32px;">
          <p style="font-size:12px; color:#999999; margin:0; line-height:18px; font-style:italic;">
            {rodape_nota}
          </p>
        </td></tr>
        <tr><td align="center" style="padding:18px 32px 30px 32px;">
          <p style="font-size:12.5px; color:#888888; margin:0; line-height:19px;">
            Caso não queira mais receber estes e-mails, <a href="#" style="color:#0c4a4a; text-decoration:underline;">cancele sua inscrição</a>.
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
{pixel_html}
</body>
</html>
"""
