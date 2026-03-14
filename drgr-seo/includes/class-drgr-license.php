<?php
/**
 * DRGR_License_Manager — handles plugin license activation, deactivation,
 * status check and admin UI.
 */
if ( ! defined( 'ABSPATH' ) ) exit;

class DRGR_License_Manager {

    private $option_key = 'drgr_seo_license';

    public function __construct() {
        add_action( 'admin_post_drgr_activate_license',   array( $this, 'handle_activate' ) );
        add_action( 'admin_post_drgr_deactivate_license', array( $this, 'handle_deactivate' ) );
    }

    // ─── Public API ──────────────────────────────────────────────────────────

    /**
     * Returns the stored license data array.
     *
     * @return array{key:string, status:string, expires:string, email:string}
     */
    public function get_license() {
        return wp_parse_args(
            get_option( $this->option_key, array() ),
            array(
                'key'     => '',
                'status'  => 'inactive',
                'expires' => '',
                'email'   => '',
            )
        );
    }

    /**
     * Returns true when the stored license is active and not expired.
     */
    public function is_license_valid() {
        $license = $this->get_license();
        if ( $license['status'] !== 'active' ) return false;
        if ( ! empty( $license['expires'] ) ) {
            $expires_ts = strtotime( $license['expires'] );
            // strtotime returns false for invalid strings — treat invalid expiry as expired
            if ( $expires_ts === false || $expires_ts < time() ) return false;
        }
        return true;
    }

    // ─── Admin UI ────────────────────────────────────────────────────────────

    public function license_interface() {
        $license  = $this->get_license();
        $is_valid = $this->is_license_valid();

        // Show queued transient message
        $msg = get_transient( 'drgr_license_msg_' . get_current_user_id() );
        if ( $msg ) {
            delete_transient( 'drgr_license_msg_' . get_current_user_id() );
        }
        ?>
        <div class="drgr-license-box">
            <h2><?php esc_html_e( 'License Management', 'drgr-seo' ); ?></h2>

            <div class="drgr-license-status <?php echo $is_valid ? 'drgr-lic-active' : 'drgr-lic-inactive'; ?>">
                <?php if ( $is_valid ) : ?>
                    ✓ <?php esc_html_e( 'License is active', 'drgr-seo' ); ?>
                    <?php if ( ! empty( $license['expires'] ) ) : ?>
                        &mdash; <?php esc_html_e( 'Expires:', 'drgr-seo' ); ?>
                        <strong><?php echo esc_html( date_i18n( get_option( 'date_format' ), strtotime( $license['expires'] ) ) ); ?></strong>
                    <?php else : ?>
                        &mdash; <?php esc_html_e( 'Lifetime license', 'drgr-seo' ); ?>
                    <?php endif; ?>
                <?php else : ?>
                    ✗ <?php esc_html_e( 'License inactive', 'drgr-seo' ); ?>
                <?php endif; ?>
            </div>

            <?php if ( $msg ) : ?>
                <div class="notice notice-<?php echo esc_attr( $msg['type'] ); ?> inline"><p><?php echo esc_html( $msg['text'] ); ?></p></div>
            <?php endif; ?>

            <?php if ( ! $is_valid ) : ?>
            <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                <input type="hidden" name="action" value="drgr_activate_license">
                <?php wp_nonce_field( 'drgr_license_activate' ); ?>
                <table class="form-table">
                    <tr>
                        <th scope="row"><label for="drgr_license_key"><?php esc_html_e( 'License Key', 'drgr-seo' ); ?></label></th>
                        <td>
                            <input type="text" id="drgr_license_key" name="license_key"
                                   value="<?php echo esc_attr( $license['key'] ); ?>"
                                   class="regular-text"
                                   placeholder="XXXX-XXXX-XXXX-XXXX"
                                   autocomplete="off">
                        </td>
                    </tr>
                    <tr>
                        <th scope="row"><label for="drgr_license_email"><?php esc_html_e( 'Email', 'drgr-seo' ); ?></label></th>
                        <td>
                            <input type="email" id="drgr_license_email" name="license_email"
                                   value="<?php echo esc_attr( $license['email'] ); ?>"
                                   class="regular-text">
                        </td>
                    </tr>
                </table>
                <?php submit_button( __( 'Activate License', 'drgr-seo' ), 'primary', 'submit', false ); ?>
            </form>
            <?php else : ?>
            <table class="form-table">
                <tr>
                    <th scope="row"><?php esc_html_e( 'License Key', 'drgr-seo' ); ?></th>
                    <td><code><?php echo esc_html( $this->mask_key( $license['key'] ) ); ?></code></td>
                </tr>
                <?php if ( ! empty( $license['email'] ) ) : ?>
                <tr>
                    <th scope="row"><?php esc_html_e( 'Email', 'drgr-seo' ); ?></th>
                    <td><?php echo esc_html( $license['email'] ); ?></td>
                </tr>
                <?php endif; ?>
            </table>
            <form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
                <input type="hidden" name="action" value="drgr_deactivate_license">
                <input type="hidden" name="license_key" value="<?php echo esc_attr( $license['key'] ); ?>">
                <?php wp_nonce_field( 'drgr_license_deactivate' ); ?>
                <?php submit_button( __( 'Deactivate License', 'drgr-seo' ), 'secondary', 'submit', false ); ?>
            </form>
            <?php endif; ?>
        </div>
        <?php
    }

    // ─── Handlers ────────────────────────────────────────────────────────────

    public function handle_activate() {
        if ( ! current_user_can( 'manage_options' ) ) wp_die( 'Forbidden' );
        check_admin_referer( 'drgr_license_activate' );

        $key   = sanitize_text_field( wp_unslash( $_POST['license_key']   ?? '' ) );
        $email = sanitize_email( wp_unslash( $_POST['license_email'] ?? '' ) );

        if ( empty( $key ) ) {
            $this->set_message( 'error', __( 'Please enter a license key.', 'drgr-seo' ) );
        } else {
            $result = $this->validate_license_remote( $key, $email );
            if ( $result['valid'] ) {
                update_option( $this->option_key, array(
                    'key'     => $key,
                    'status'  => 'active',
                    'expires' => $result['expires'],
                    'email'   => $email,
                ) );
                $this->set_message( 'success', __( 'License activated successfully!', 'drgr-seo' ) );
            } else {
                $this->set_message( 'error', $result['message'] );
            }
        }

        wp_safe_redirect( admin_url( 'options-general.php?page=drgr-seo-settings' ) );
        exit;
    }

    public function handle_deactivate() {
        if ( ! current_user_can( 'manage_options' ) ) wp_die( 'Forbidden' );
        check_admin_referer( 'drgr_license_deactivate' );

        $key = sanitize_text_field( wp_unslash( $_POST['license_key'] ?? '' ) );

        // Optionally notify remote server
        $this->deactivate_license_remote( $key );

        update_option( $this->option_key, array(
            'key'     => '',
            'status'  => 'inactive',
            'expires' => '',
            'email'   => '',
        ) );
        $this->set_message( 'info', __( 'License deactivated.', 'drgr-seo' ) );

        wp_safe_redirect( admin_url( 'options-general.php?page=drgr-seo-settings' ) );
        exit;
    }

    // ─── Remote validation ───────────────────────────────────────────────────

    /**
     * Validate the license key against the remote licensing server.
     *
     * Replace the URL and response handling below with your actual server logic.
     *
     * @param string $key
     * @param string $email
     * @return array{valid:bool, expires:string, message:string}
     */
    private function validate_license_remote( $key, $email ) {
        /*
         * Example remote call — swap in your endpoint:
         *
         * $response = wp_remote_post( 'https://license.drgr.ru/api/v1/activate', array(
         *     'timeout' => 15,
         *     'body'    => array(
         *         'license_key' => $key,
         *         'email'       => $email,
         *         'domain'      => home_url(),
         *         'plugin'      => 'drgr-seo',
         *     ),
         * ) );
         *
         * if ( is_wp_error( $response ) ) {
         *     return array( 'valid' => false, 'expires' => '', 'message' => $response->get_error_message() );
         * }
         *
         * $body = json_decode( wp_remote_retrieve_body( $response ), true );
         * return array(
         *     'valid'   => ! empty( $body['valid'] ),
         *     'expires' => $body['expires'] ?? '',
         *     'message' => $body['message'] ?? __( 'License validation failed.', 'drgr-seo' ),
         * );
         */

        // ── Local format validation (active until remote server is set up) ──
        // Accepts formats: XXXX-XXXX-XXXX-XXXX or any 16+ alphanumeric characters.
        if ( preg_match( '/^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$/i', $key ) || strlen( $key ) >= 16 ) {
            return array( 'valid' => true, 'expires' => '', 'message' => 'OK' );
        }

        return array(
            'valid'   => false,
            'expires' => '',
            'message' => __( 'Invalid license key format. Expected XXXX-XXXX-XXXX-XXXX.', 'drgr-seo' ),
        );
    }

    /**
     * Notify the remote server that this license is being deactivated.
     */
    private function deactivate_license_remote( $key ) {
        /*
         * wp_remote_post( 'https://license.drgr.ru/api/v1/deactivate', array(
         *     'timeout' => 10,
         *     'body'    => array( 'license_key' => $key, 'domain' => home_url() ),
         * ) );
         */
    }

    // ─── Helpers ─────────────────────────────────────────────────────────────

    private function set_message( $type, $text ) {
        set_transient( 'drgr_license_msg_' . get_current_user_id(), compact( 'type', 'text' ), 60 );
    }

    private function mask_key( $key ) {
        if ( strlen( $key ) <= 8 ) return str_repeat( '*', strlen( $key ) );
        return substr( $key, 0, 4 ) . str_repeat( '*', strlen( $key ) - 8 ) . substr( $key, -4 );
    }
}
